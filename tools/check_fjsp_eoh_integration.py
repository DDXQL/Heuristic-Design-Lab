"""Strict caller, durable failure, prefix curves: synthetic wire, ZERO model/solve."""
from pathlib import Path
from contextlib import ExitStack,redirect_stdout,redirect_stderr
from unittest.mock import patch
from types import SimpleNamespace
import copy,io,os,tempfile,unittest,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.problems.fjsp import eoh_single as e
from heuristic_design.core import execution
from heuristic_design.core.storage import read,write,sha
from heuristic_design.llm.strict_nonstream import admit,StrictNonstreamTransport
from fjsp_usage.research_real.real_transport import JsonCandidateTransport,TransportError,decode_chat

MODEL='gpt-6.1-sol'
def reply(text='complete text'):
    return dict(text=text,usage=dict(input_tokens=12,output_tokens=3),metadata=dict(http_status=200,model=MODEL,finish_reason='stop',refusal_present=False,tool_calls_present=False))
class FixtureWireAdapter(e.Adapter):
    def transport(self,p):return StrictNonstreamTransport(self.client_config(p))

class Checks(unittest.TestCase):
    def setUp(self):
        (ROOT/'runs').mkdir(exist_ok=True);self.tmp=tempfile.TemporaryDirectory(prefix='fjsp-integration-offline-',dir=ROOT/'runs');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.c=read(ROOT/'experiments/common/configs/fjsp-eoh-single.mock.json')
        self.c['provider'].update(stream_response=False,api_key_env='FJSP_EOH_OFFLINE_TEST_KEY')
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{'FJSP_EOH_OFFLINE_TEST_KEY':'OFFLINE_FIXTURE_NOT_A_REAL_KEY'}))
        self.stack.enter_context(redirect_stdout(io.StringIO()));self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('NO INTERNET')))
        self.stack.enter_context(patch('heuristic_design.problems.tsp.h_build.evaluate_task',side_effect=AssertionError('NO SOLVE')))
    def prepare(self,name,changes=None):
        p=self.root/(name+'.json');write(p,{**self.c,**(changes or {})});run=self.root/name;e.prepare(run,p);return run
    def fixture(self,key,prompt,*,kind,on_sent):
        on_sent();i=int(key.split('/H-')[-1].split('/')[0])
        return reply('{Fixed H fixture.}\n```python\n'+e.TEMPLATE.replace('0.0',f'-processing_time + {i/100!r} * remaining_work')+'```')
    def test_saved_two_upstream_responses_pass_transport_not_H_parser(self):
        for i in ('01','02'):
            v=read(ROOT/f'reports/fjsp-eoh-client-integrated-20261104/upstream-response-{i}.json')
            self.assertIs(admit(v,MODEL),v)
            with self.assertRaises(e.CandidateError):e.Adapter().parse_candidate(v['text'],self.c)
    def test_usage_is_mandatory_and_invalid_values_rejected(self):
        for usage in (None,{},dict(input_tokens=True,output_tokens=1),dict(input_tokens=-1,output_tokens=1)):
            v=reply();v['usage']=usage
            with self.assertRaises(TransportError) as caught:admit(v,MODEL)
            self.assertTrue(caught.exception.metadata['caller_hard_stop'])
    def test_model_finish_refusal_tools_and_empty_text_rejected(self):
        cases=[]
        for key,value in [('model','wrong'),('finish_reason','length'),('refusal_present',True),('tool_calls_present',True),('http_status',403)]:
            v=reply();v['metadata'][key]=value;cases.append(v)
        cases.append(reply(''))
        for v in cases:
            with self.assertRaises(TransportError):admit(v,MODEL)
    def test_common_decoder_preserves_strict_model_and_completion(self):
        provider=SimpleNamespace(protocol='openai-chat-v1',expected_response_model=MODEL)
        data=dict(id='local',model=MODEL,usage=dict(prompt_tokens=12,completion_tokens=3),choices=[dict(finish_reason='stop',message=dict(content='H code'))])
        good=decode_chat(data,provider);self.assertEqual(good['usage']['output_tokens'],3)
        for field,value in [('model','wrong'),('choices',[dict(finish_reason='length',message=dict(content='partial'))])]:
            bad=copy.deepcopy(data);bad[field]=value
            with self.assertRaises(TransportError):decode_chat(bad,provider)
        missing=copy.deepcopy(data);missing.pop('usage');wire=decode_chat(missing,provider)
        wire['metadata']['http_status']=200
        with self.assertRaises(TransportError):admit(wire,MODEL)
    def test_missing_usage_first_failure_committed_then_persistent_stop(self):
        run=self.prepare('missing')
        def missing(*args,**kwargs):v=self.fixture(*args,**kwargs);v['usage']=None;return v
        with patch.object(JsonCandidateTransport,'dispatch',side_effect=missing) as send:
            r=execution.start(run,adapter=FixtureWireAdapter());self.assertEqual(r['phase'],'paused');self.assertEqual(send.call_count,1)
        p,s=e.protocol_state(run);self.assertEqual(s['cursor'],1);self.assertEqual(s['eoh']['initialization_requests'],1)
        self.assertFalse((run/'.execution.lock').exists());self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),1)
        self.assertEqual(read(run/'API_attempts.json')['halt_reason'],'strict_nonstream_response_rejected')
        rejected=list((run/'caller_rejections').glob('*.json'));self.assertEqual(len(rejected),1)
        self.assertIsNone(read(rejected[0])['normalized_response']['usage'])
        with self.assertRaises(ValueError):execution.start(run,adapter=FixtureWireAdapter(),resume=True)
    def test_execution_default_other_adapter_does_not_opt_into_settlement(self):
        class OtherAdapter(FixtureWireAdapter):settle_known_api_stop=False
        run=self.prepare('default-controller')
        def refusal(*args,**kwargs):
            kwargs['on_sent']();error=TransportError('HTTP status 403');error.metadata={'http_status':403};raise error
        with patch.object(JsonCandidateTransport,'dispatch',side_effect=refusal):
            self.assertEqual(execution.start(run,adapter=OtherAdapter())['phase'],'stopped')
        self.assertEqual(read(run/'checkpoint.json')['cursor'],0);self.assertTrue((run/'.execution.lock').exists())
    def test_HTTP403_stops_first_and_does_not_consume_remaining_budget(self):
        run=self.prepare('403')
        def refusal(*args,**kwargs):
            kwargs['on_sent']();error=TransportError('HTTP status 403');error.metadata={'http_status':403};raise error
        with patch.object(JsonCandidateTransport,'dispatch',side_effect=refusal) as send:
            r=execution.start(run,adapter=FixtureWireAdapter());self.assertEqual(r['phase'],'paused');self.assertEqual(send.call_count,1)
        self.assertEqual(read(run/'checkpoint.json')['cursor'],1);self.assertFalse((run/'.execution.lock').exists())
    def test_repeated_524_pause_then_explicit_resume_preserves_clock_and_no_replay(self):
        run=self.prepare('524');calls=[]
        def transient(key,*args,**kwargs):
            calls.append(key);i=int(key.split('/H-')[-1].split('/')[0])
            if i<3:
                kwargs['on_sent']();error=TransportError('HTTP status 524');error.metadata={'http_status':524};raise error
            return self.fixture(key,*args,**kwargs)
        with patch.object(JsonCandidateTransport,'dispatch',side_effect=transient):
            self.assertEqual(execution.start(run,adapter=FixtureWireAdapter())['phase'],'paused')
            before=read(run/'checkpoint.json');clock=(run/'Run_clock.json').read_bytes();self.assertEqual(before['cursor'],3)
            self.assertEqual(execution.start(run,adapter=FixtureWireAdapter(),resume=True)['phase'],'completed')
        self.assertEqual(len(calls),12);self.assertEqual(len(set(calls)),12);self.assertEqual(clock,(run/'Run_clock.json').read_bytes())
    def test_valid_transport_invalid_H_is_scientific_failure_not_infrastructure_stop(self):
        run=self.prepare('parse')
        def invalid(key,*args,**kwargs):
            v=self.fixture(key,*args,**kwargs)
            if 'H-0003/' in key:v['text']='a valid complete response with no H function'
            return v
        with patch.object(JsonCandidateTransport,'dispatch',side_effect=invalid):
            self.assertEqual(execution.start(run,adapter=FixtureWireAdapter())['phase'],'completed')
        self.assertIsNone(read(run/'API_attempts.json')['halt_reason']);self.assertEqual(read(run/'checkpoint.json')['cursor'],12)
    def test_formal_prepare_requires_new_CLI_approval_and_only_freezes_files(self):
        cfg=ROOT/'experiments/common/configs/fjsp-eoh-single.real.json'
        with patch.object(e,'StrictNonstreamTransport',side_effect=AssertionError('NO TRANSPORT CONSTRUCTION')):
            with self.assertRaises(PermissionError):e.prepare(self.root/'no',cfg,allow_api=True,approve_budget=1000)
            with patch.dict(os.environ,{'LEAFAPI_API_KEY':''}):
                with self.assertRaises(ValueError):e.prepare(self.root/'missing-key',cfg,allow_api=True,approve_budget=1050)
            # Ephemeral unit fixture simulates matching CLI flags, never launches execution.
            with patch.dict(os.environ,{'LEAFAPI_API_KEY':'OFFLINE_UNIT_FIXTURE_NOT_A_KEY'}):
                e.prepare(self.root/'file-only-test',cfg,allow_api=True,approve_budget=1050)
        p,s=e.protocol_state(self.root/'file-only-test');self.assertEqual(s['phase'],'prepared')
        self.assertFalse((self.root/'file-only-test/API_attempts.json').exists());self.assertFalse((self.root/'file-only-test/Launch_authorization.json').exists())
        self.assertEqual(p['config']['api_concurrency'],1);self.assertFalse(read(cfg)['real_requests_authorized'])
    def test_source_binding_tamper_and_provider_change_rejected(self):
        c=e.settings(ROOT/'experiments/common/configs/fjsp-eoh-single.real.json');bad=copy.deepcopy(c);bad['provider']['stream_response']=True
        with self.assertRaises(ValueError):e.transport_status(bad)
        bad=copy.deepcopy(c);bad['transport_binding']['sha256']='0'*64
        with self.assertRaises(ValueError):e.transport_status(bad)
    def test_physical_curve_counts_only_complete_valid_unique_and_retains_reservations(self):
        tasks={}
        for i in range(5):
            tasks[f'H-{i:04d}']=dict(status='completed',valid=i in (0,1,4),fitness=-2. if i==4 else -2.1,
                candidate=dict(key='a' if i<2 else 'c'),AST_duplicate=i==1,failure='evaluation_invalid' if i==3 else None)
        journal=dict(api_attempts={str(i):dict(logical_id=f'H-{i:04d}',status='failed') for i in range(1050)})
        curve=e.progress_curve(dict(tasks=tasks,cursor=5),journal)
        self.assertEqual(len(curve),1051);self.assertEqual(curve[1023]['full_valid_unique_H_evaluations'],2)
        self.assertEqual(curve[1050]['committed_tasks'],5);self.assertFalse(curve[1050]['latest_task_committed'])
        self.assertEqual(curve[2]['full_valid_unique_H_evaluations'],1);self.assertEqual(curve[5]['best_fitness'],-2.)
    def test_export_nodes_curves_and_engineering_freeze_are_explicit(self):
        run=self.prepare('export');execution.start(run,adapter=e.Adapter());summary=e.export(run)
        self.assertTrue(summary['engineering_only']);self.assertEqual(summary['curve_attempts_reserved'],12)
        self.assertTrue((run/'analysis/progress_curve.csv').exists());self.assertTrue((run/'analysis/budget_nodes.csv').exists())
        self.assertTrue((run/'analysis/frozen_engineering_candidate.json').exists());self.assertFalse((run/'analysis/frozen_training_champion.json').exists())
        self.assertTrue(read(run/'analysis/Plot_status.json')['passed'],read(run/'analysis/Plot_status.json'))

if __name__=='__main__':unittest.main(verbosity=2)
