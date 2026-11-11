"""No model or policy execution. Synthetic receipts and local HTTP only."""
import importlib.util,io,json,os,socket,ssl,tempfile,types,unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from fjsp_usage.research_real import real_transport as t
from fjsp_usage.research_real.config import ProviderConfig,ExperimentConfig
from heuristic_design.core import execution as e
from heuristic_design.core.storage import read,write,sha
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('v5diagnostic',ROOT/'tools/api_reliability_next.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class NetworkTests(unittest.TestCase):
    def provider(self,url='https://localhost/chat'):return ProviderConfig(url,'alias',protocol='openai-chat-v1',expected_response_model='locked',connect_timeout=.1,read_timeout=.1,total_timeout=1,temperature=None)
    def worker(self,phase):
        class Pipe:
            def __init__(self):self.messages=[]
            def send(self,x):self.messages.append(__import__('copy').deepcopy(x))
            def close(self):pass
        class Sock:
            def settimeout(self,x):pass
            def bind(self,x):pass
            def connect(self,target):
                if phase=='tcp':raise TimeoutError('fixture')
            def close(self):pass
        class Conn:
            def __init__(self,*a,**kw):self.sock=None
            def connect(self):
                self.sock=self._create_connection(('localhost',443),.1,None)
                if phase=='tls':raise ssl.SSLCertVerificationError('fixture')
            def close(self):pass
        pipe=Pipe()
        with patch.object(t.socket,'getaddrinfo',side_effect=socket.gaierror('fixture') if phase=='dns' else None,return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',1))]),patch.object(t.socket,'socket',return_value=Sock()),patch.object(t.http.client,'HTTPSConnection',Conn):
            t._wire_worker(pipe,self.provider(),{'model':'alias','messages':[{'role':'user','content':'fixture'}]},'')
        return pipe.messages[-1]
    def test_dns_tcp_tls_failures_are_separate_and_unsent(self):
        for phase,category in [('dns','dns_failure'),('tcp','tcp_connection_failure'),('tls','tls_failure')]:
            with self.subTest(phase=phase):
                m=self.worker(phase);self.assertEqual(m['kind'],'error');self.assertEqual(m['metadata']['connection_phase'],phase)
                self.assertEqual(m['metadata']['send_status'],'not_started');self.assertEqual(t.failure_category(m['error'],m['metadata']),category)
    def test_historical_sse_id_error_classification(self):
        self.assertEqual(t.failure_category('',{'http_status':200,'identity_change':{'field':'id'}}),'sse_id_changed')
    def test_routing_and_eoh_share_strict_nonstream_usage_gate(self):
        from heuristic_design.llm.routing_transport import generate
        value={'text':'{fixture}', 'usage':None,'metadata':{'http_status':200,'model':'locked','finish_reason':'stop'}}
        config={'api_mode':'real','real_requests_authorized':True,'api_attempt_cap':1,'provider':asdict(self.provider())}
        config['provider']['api_key_env']='V5_UNIT_SECRET'
        with patch.dict(os.environ,{'V5_UNIT_SECRET':'fixture'}),patch.object(t.JsonCandidateTransport,'dispatch',return_value=value):
            r=generate({'request_key':'local'},'fixture',config,10)
        self.assertIsNone(r['text']);self.assertTrue(r['metadata']['caller_hard_stop'])
    def test_invalid_json_preserves_body_hash_and_classification(self):
        from fjsp_usage.research_real.fixtures import fixture_server
        with fixture_server(responder=lambda payload,index:{},script=[{'malformed':True}]) as (url,traffic):
            with self.assertRaises(t.TransportError) as cm:t.JsonCandidateTransport(ExperimentConfig(self.provider(url))).dispatch('one','fixture')
            m=cm.exception.metadata
            self.assertEqual(t.failure_category(str(cm.exception),m),'invalid_json_response')
            self.assertEqual(m['response_body_bytes'],8);self.assertEqual(len(m['response_body_sha256']),64)
            self.assertEqual(len(traffic['requests']),1)
    def test_exact_shared_payload_and_network_mode(self):
        from fjsp_usage.research_real.fixtures import fixture_server
        def response(payload,index):return {'model':'locked','id':'local','choices':[{'message':{'content':'fixture'},'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':3}}
        with fixture_server(responder=response) as (url,traffic):
            cfg=ExperimentConfig(self.provider(url));v=t.JsonCandidateTransport(cfg).dispatch('one','fixture')
            self.assertEqual(len(traffic['requests']),1)
            times=v['metadata']['wire_timing'];self.assertIn('dns_completed_seconds',times);self.assertIn('tcp_completed_seconds',times)
            self.assertFalse(v['metadata']['connection']['application_proxy']);self.assertEqual(v['usage']['output_tokens'],3)

class LifecycleTests(unittest.TestCase):
    def test_settled_clock_gap_commits_once_pauses_then_resumes_same_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);calls=[]
            p={'config':{'api_mode':'mock','window_seconds':10000,'search_seed':1,'type':'one','per_candidate_attempt_cap':1,'provider':{'total_timeout':1}},'instances':[],'budgets':{'logical_generation':2,'max_program_instances':0}}
            write(root/'Protocol.json',p);write(root/'Tasks.json',[{'id':'t0','stage':'new','generation':None},{'id':'t1','stage':'new','generation':None}])
            state={'identity':sha(root/'Protocol.json'),'phase':'launching','cursor':0,'tasks':{},'evaluations':{},'pause_ack':0,'population':[],'generation':0}
            write(root/'checkpoint.json',state);write(root/'Launch_authorization.json',{'protocol':state['identity'],'explicit_cli_allow_api':False});write(root/'.execution.lock',{'fixture':True})
            class Journal:
                data={'halt_reason':None}
                def request(self,tid,*a,**kw):calls.append(tid);return {'status':'failed','attempt_ids':[]}
            class Adapter:
                ROOT=root;entrypoint='unused';sha=staticmethod(sha);read=staticmethod(read);write=staticmethod(write)
                def check_run(self,directory):return p
                def members(self,directory):return []
                def journal(self,*a):return Journal()
                def build_prompt(self,*a):return 'synthetic receipt only'
                def summary(self,*a,**kw):return {}
                def commit_candidate(self,*a):pass
            # No strategy object is parsed or evaluated, no request dispatched.
            wall=iter([1000,1000,1000,1000,1100,1100,1100])
            fake=types.SimpleNamespace(time=lambda:next(wall),monotonic=lambda:100 if not calls else 110,time_ns=lambda:1)
            with patch.object(e,'time',fake),patch.object(e.sys,'platform','linux'),patch.object(e.signal,'signal'):
                result=e.work(root,adapter=Adapter())
            self.assertEqual(result['phase'],'paused');s=read(root/'checkpoint.json');self.assertEqual(s['cursor'],1)
            self.assertEqual(calls,['t0']);self.assertTrue(read(root/'Clock_quarantine.json')['task_committed']);self.assertFalse((root/'.execution.lock').exists())
            deadline=read(root/'Run_clock.json')['deadline']
            fake=types.SimpleNamespace(time=lambda:1100,monotonic=lambda:200,time_ns=lambda:2)
            with patch.object(e,'time',fake),patch.object(e.sys,'platform','linux'),patch.object(e.signal,'signal'):
                result=e.start(root,adapter=Adapter(),resume=True)
            self.assertEqual(result['phase'],'completed');self.assertEqual(calls,['t0','t1']);self.assertEqual(read(root/'Run_clock.json')['deadline'],deadline)

class DiagnosticTests(unittest.TestCase):
    def fixture(self,fn):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);planfile=base/'plan.json';planfile.write_text('{}')
            p=json.loads(d.PLAN.read_text());p['provider']['api_key_env']='V5_FIXTURE_KEY'
            provider=ProviderConfig(**p['provider']);calls=[]
            class Transport:
                def __init__(self,cfg):self.provider=provider
                def preflight(self,prompt):pass
                def redact(self,s):return s.replace('fixture-secret','[REDACTED]')
                def redact_metadata(self,m):return t.redact_diagnostic(m,'fixture-secret')
                def dispatch(self,key,prompt,**kw):
                    calls.append(key);kw['on_sent']();kind='fjsp_h' if key.endswith('fjsp_h') else 'tsp_u'
                    value=json.loads((ROOT/f'deploy/api-common/replay/{kind}_success.json').read_text())
                    value['metadata']['send_status']='confirmed';return value
            with patch.object(d,'verify',return_value=p),patch.object(d,'PLAN',planfile),patch.object(d,'directory',side_effect=lambda site:base/site),patch.object(d,'StrictNonstreamTransport',Transport),patch.dict(os.environ,{'V5_FIXTURE_KEY':'fixture-secret','SLURM_JOB_ID':'fixture'}),patch.object(d.sys,'platform','darwin'),patch.object(d.socket,'gethostname',return_value='nodefixture'),patch.object(socket.socket,'connect',side_effect=AssertionError('NO INTERNET')):
                fn(p,base,calls,Transport)
    def test_explicit_new_authorization_and_cap_required(self):
        def check(p,b,c,T):
            for kw in ({},{'allow_api':True,'approve_total':8}):
                with self.assertRaises(PermissionError):d.run('mac',**kw)
            self.assertFalse((b/'mac/claim.json').exists());self.assertEqual(c,[])
        self.fixture(check)
    def test_both_sites_serial_no_retry_and_export_chain_cap4(self):
        def check(p,b,c,T):
            first=d.run('mac',allow_api=True,approve_total=4)
            second=d.run('cluster',allow_api=True,approve_total=4,mac_export=b/'mac/export.json')
            self.assertEqual(first['status'],'completed');self.assertEqual(second['status'],'completed');self.assertEqual(len(c),4)
            self.assertEqual(second['prior_new_reserved']+len(second['records']),4)
            with self.assertRaises(FileExistsError):d.run('mac',allow_api=True,approve_total=4)
            self.assertEqual(len(c),4)
        self.fixture(check)
    def test_active_controller_excludes_second_launch(self):
        def check(p,b,c,T):
            import threading
            entered=threading.Event();release=threading.Event();original=T.dispatch;result=[]
            def held(self,*a,**kw):
                value=original(self,*a,**kw)
                if len(c)==1:entered.set();release.wait(3)
                return value
            def worker():result.append(d.run('mac',allow_api=True,approve_total=4))
            with patch.object(T,'dispatch',held):
                thread=threading.Thread(target=worker);thread.start();self.assertTrue(entered.wait(3))
                try:
                    with self.assertRaises(ValueError):d.run('mac',allow_api=True,approve_total=4)
                finally:release.set();thread.join(4)
            self.assertFalse(thread.is_alive());self.assertEqual(len(c),2);self.assertEqual(result[0]['status'],'completed')
        self.fixture(check)
    def test_stop_and_safe_resume_do_not_replay_first_slot(self):
        def check(p,b,c,T):
            original=T.dispatch
            def one(self,*a,**kw):
                value=original(self,*a,**kw);d.save(b/'mac/Stop_request.json',{'sequence':1});return value
            with patch.object(T,'dispatch',one):first=d.run('mac',allow_api=True,approve_total=4)
            self.assertEqual(first['status'],'paused');self.assertEqual(len(c),1)
            with self.assertRaises(ValueError):d.prior_receipt(b/'mac/export.json',p)
            second=d.run('mac',allow_api=True,approve_total=4,resume=True)
            self.assertEqual(second['status'],'completed');self.assertEqual(len(c),2);self.assertEqual(c,['mac-fjsp_h','mac-tsp_u'])
        self.fixture(check)
    def test_diagnostic_local_clock_gap_pauses_after_settlement(self):
        def check(p,b,c,T):
            import time as real_time
            shifted=[False];original=T.dispatch
            def shifted_dispatch(self,*a,**kw):
                value=original(self,*a,**kw);shifted[0]=True;return value
            fake=types.SimpleNamespace(time=lambda:real_time.time()+(90 if shifted[0] else 0),
                monotonic=real_time.monotonic,get_clock_info=real_time.get_clock_info)
            with patch.object(d,'time',fake),patch.object(T,'dispatch',shifted_dispatch):r=d.run('mac',allow_api=True,approve_total=4)
            self.assertEqual(r['status'],'paused');self.assertEqual(len(c),1)
            self.assertTrue(r['clock_events'][0]['settled']);self.assertEqual(r['records'][0]['status'],'passed')
        self.fixture(check)
    def test_refusal_stops_stage_and_blocks_cluster(self):
        def check(p,b,c,T):
            def refuse(self,key,*a,**kw):
                c.append(key);kw['on_sent']();error=t.TransportError('HTTP status 401');error.metadata={'http_status':401,'send_status':'confirmed'};raise error
            with patch.object(T,'dispatch',refuse):r=d.run('mac',allow_api=True,approve_total=4)
            self.assertEqual(len(c),1);self.assertTrue(r['global_hard_stop']);self.assertEqual(r['status'],'failed_closed')
            with self.assertRaises(ValueError):d.run('cluster',allow_api=True,approve_total=4,mac_export=b/'mac/export.json')
        self.fixture(check)
    def test_unknown_interruption_never_resumes_or_replays(self):
        def check(p,b,c,T):
            def unknown(self,*a,**kw):raise KeyboardInterrupt()
            with patch.object(T,'dispatch',unknown),self.assertRaises(KeyboardInterrupt):d.run('mac',allow_api=True,approve_total=4)
            r=d.read(b/'mac/ledger.json');self.assertEqual(r['status'],'unknown_interruption');self.assertEqual(r['totals']['send_unknown'],1)
            with self.assertRaises(ValueError):d.run('mac',allow_api=True,approve_total=4,resume=True)
        self.fixture(check)
    def test_export_tamper_and_invalid_candidates(self):
        def check(p,b,c,T):
            d.run('mac',allow_api=True,approve_total=4);v=d.read(b/'mac/export.json');v['ledger']['records'][0]['usage']={'input_tokens':0,'output_tokens':0};d.save(b/'tampered.json',v)
            with self.assertRaises(ValueError):d.prior_receipt(b/'tampered.json',p)
            self.assertEqual(d.parse_candidate('no fence','fjsp_h')['failure_layer'],'candidate_extraction')
            self.assertEqual(d.parse_candidate('{rule}\n```python\ndef wrong():\n return 1\n```','fjsp_h')['failure_layer'],'code_constraint')
        self.fixture(check)
    def test_bundle_reuse_verifies_source_plan_and_receipt_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);receipt=root/'fixture-export.json';receipt.write_text('{"offline_fixture":true}')
            with patch.object(d,'OUTBOX',root/'outbox'),patch.object(d,'prior_receipt',return_value={}):
                archive=d.bundle(receipt);before=archive.read_bytes()
                self.assertEqual(d.bundle(receipt),archive);self.assertEqual(archive.read_bytes(),before)
                receipt.write_text('{"offline_fixture":"changed"}')
                with self.assertRaises(ValueError):d.bundle(receipt)
                self.assertEqual(archive.read_bytes(),before)
    def test_check_and_replay_are_offline_and_do_not_read_credentials(self):
        original=os.environ.get
        def guarded(name,*a):
            if name=='LEAFAPI_API_KEY':raise AssertionError('NO KEY READ')
            return original(name,*a)
        with patch.object(os.environ,'get',side_effect=guarded),patch.object(d,'StrictNonstreamTransport',side_effect=AssertionError('NO TRANSPORT')),patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK')):
            self.assertEqual(len(d.replay()['cases']),5)
            with patch('sys.argv',['entry','check-only']),patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(d.main(),0)
if __name__=='__main__':unittest.main()
