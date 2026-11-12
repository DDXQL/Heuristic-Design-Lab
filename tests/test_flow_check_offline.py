"""Flow control with synthetic receipts only. No candidate, solve or HTTP executes."""
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import tempfile
import types
import unittest
from dataclasses import asdict
from unittest.mock import patch

from heuristic_design.core import flow_check as f
from heuristic_design.core.storage import read,write,sha,digest
from fjsp_usage.research_real.real_transport import TransportError

ROOT=Path(__file__).resolve().parents[1]


class FlowTests(unittest.TestCase):
    def fixture(self,fn,*,invalid=False,refused=False,unknown=False,gap=False):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve();calls=[];evals=[];shifted=[False]
            original_time=f.execution.time
            class Wire:
                def __init__(self,config):
                    self.config=config;self.provider=config.provider;self.secret='fixture-only';self.identity='synthetic-receipt-wire'
                def redact(self,text):return text.replace('fixture-only','[REDACTED]')
                def preflight(self,prompt):pass
                def dispatch(self,key,prompt,*,kind='h',on_sent):
                    role='state_A_U' if 'state_A_U' in key else 'single_H_sample'
                    calls.append(role);on_sent()
                    if refused:
                        error=TransportError('fixture HTTP401');error.metadata={'http_status':401,'failure_stage':'http_receive','send_status':'confirmed'};error.usage=None;raise error
                    code=('def use_heuristics(state):\n    return 0\n' if role=='state_A_U' else
                          'def priority(processing_time, remaining_work, remaining_operations, job_ready_time, machine_ready_time, earliest_start, earliest_finish):\n    return -processing_time + remaining_work * 0.01\n')
                    return {'text':'{Synthetic receipt only, never an actual model call.}\n```python\n'+code+'```',
                            'usage':{'input_tokens':3,'output_tokens':5},
                            'metadata':{'http_status':200,'model':'gpt-6.1-sol','finish_reason':'stop','send_status':'confirmed'}}
            def evaluation(directory,state,p,c):
                evals.append(c.role);folder=directory/'evaluations'/c.key;folder.mkdir(parents=True)
                state['evaluations'][c.key]={'status':'reserved','maximum_solve_passes':2,'role':c.role};write(directory/'checkpoint.json',state)
                if unknown:raise RuntimeError('synthetic unknown worker reservation; NO worker was launched')
                value={'valid':not invalid,'fitness':None if invalid else 0.,'failure_layer':'candidate_runtime' if invalid else None,
                    'failure':{'error_type':'ValueError','error':'synthetic invalid receipt'} if invalid else None,
                    'instances':[] if invalid else [{'file':p['instances'][0]['file'],'score':0.,'raw_cost':1.,'reference':1.,
                        'captured_solves':2,'semantic_sha256':digest(c.role)}]}
                write(folder/'result.json',value)
                state['evaluations'][c.key]={'status':'completed','path':str((folder/'result.json').relative_to(directory)),
                    'sha256':sha(folder/'result.json'),'maximum_solve_passes':2,'role':c.role}
                write(directory/'checkpoint.json',state);shifted[0]=True
                return value,False
            fake_time=types.SimpleNamespace(time=lambda:original_time.time()+(90 if gap and shifted[0] else 0),
                monotonic=original_time.monotonic,time_ns=original_time.time_ns)
            with patch.object(f,'directory',side_effect=lambda site:base/site),patch.object(f,'sys_platform',return_value='darwin'), \
                    patch.object(f.execution.sys,'platform','linux'),patch.object(f.socket,'gethostname',return_value='nodefixture'), \
                    patch.dict(os.environ,{'LEAFAPI_API_KEY':'fixture-only','SLURM_JOB_ID':'fixture'}), \
                    patch.object(f,'StrictNonstreamTransport',Wire),patch.object(f.Adapter,'evaluate',staticmethod(evaluation)), \
                    patch.object(f.Adapter,'validate_result',staticmethod(lambda *a:None)),patch.object(f,'validate_result',lambda *a:None), \
                    patch.object(f.lifecycle,'collect',side_effect=AssertionError('NO WORKER/SOLVER')), \
                    patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK')),patch.object(f.execution,'time',fake_time):
                fn(base,calls,evals)

    def args(self):return {'allow_api':True,'approve_api':2,'allow_evaluation':True,'approve_solves':12}

    def test_new_explicit_budget_and_evaluation_gate_before_claim(self):
        def check(base,calls,evals):
            for args in [{},{'allow_evaluation':True,'approve_solves':12},{**self.args(),'approve_api':4},
                         {**self.args(),'approve_solves':24}]:
                with self.assertRaises(PermissionError):f.run('mac',**args)
                self.assertFalse((base/'mac').exists())
            self.assertEqual(calls,[]);self.assertEqual(evals,[])
        self.fixture(check)

    def test_same_coordinator_planned_pause_resume_and_both_sites_no_extra_api(self):
        def check(base,calls,evals):
            before=signal.getsignal(signal.SIGINT)
            result=f.run('mac',**self.args());self.assertEqual(result['phase'],'completed',read(base/'mac/Stop.json') if (base/'mac/Stop.json').exists() else result)
            mac=read(base/'mac/export.json');s=mac['checkpoint'];self.assertEqual(len(s['resume_checks']),1)
            self.assertEqual(s['resume_checks'][0]['clock_sha256'],s['clock_sha256'])
            self.assertEqual(mac['summary']['api_reserved'],2);self.assertEqual(mac['summary']['api_confirmed'],2)
            self.assertEqual(signal.getsignal(signal.SIGINT),before)
            result=f.run('cluster',allow_evaluation=True,approve_solves=12,mac_export=base/'mac/export.json')
            self.assertEqual(result['phase'],'completed');self.assertEqual(calls,list(f.ROLES[1:]))
            final=read(base/'cluster/export.json');self.assertTrue(final['cross_platform_passed'])
            self.assertEqual(final['summary']['api_reserved'],0)
            self.assertEqual(len(evals),6)  # six SYNTHETIC receipts, no actual solve
            self.assertEqual(final['summary']['known_solve_passes'],6)
            with self.assertRaises(FileExistsError):f.run('mac',**self.args())
            self.assertEqual(len(calls),2)
        self.fixture(check)

    def test_first_invalid_baseline_closes_before_model_requests(self):
        def check(base,calls,evals):
            result=f.run('mac',**self.args());self.assertEqual(result['phase'],'stopped')
            self.assertEqual(calls,[]);self.assertEqual(evals,['fixed_H0'])
            self.assertTrue((base/'mac/Known_failure.json').exists())
            with self.assertRaises(ValueError):f.run('mac',resume=True,**self.args())
        self.fixture(check,invalid=True)

    def test_refusal_closes_after_first_new_request_without_fill(self):
        def check(base,calls,evals):
            result=f.run('mac',**self.args());self.assertEqual(result['phase'],'stopped')
            self.assertEqual(calls,['single_H_sample']);self.assertEqual(evals,['fixed_H0'])
            self.assertEqual(read(base/'mac/Summary.json')['api_reserved'],1)
            with self.assertRaises(ValueError):f.accept_mac_export(base/'mac/export.json')
        self.fixture(check,refused=True)

    def test_unknown_evaluation_preserves_lock_reservation_and_no_resume(self):
        def check(base,calls,evals):
            result=f.run('mac',**self.args());self.assertEqual(result['phase'],'stopped')
            self.assertTrue((base/'mac/.execution.lock').exists())
            self.assertEqual(read(base/'mac/Summary.json')['unknown_solve_usage_reservations'],1)
            with self.assertRaises(ValueError):f.run('mac',resume=True,**self.args())
            self.assertEqual(calls,[]);self.assertEqual(len(evals),1)
        self.fixture(check,unknown=True)

    def test_clock_gap_settles_baseline_without_automatic_resume(self):
        def check(base,calls,evals):
            result=f.run('mac',**self.args());self.assertEqual(result['phase'],'paused')
            s=read(base/'mac/checkpoint.json');self.assertEqual(s['cursor'],1)
            self.assertEqual(s['pause_reason'],'local_clock_gap_after_settled_task')
            self.assertEqual(calls,[]);self.assertEqual(len(evals),1)
            self.assertFalse((base/'mac/.execution.lock').exists())
        self.fixture(check,gap=True)

    def test_manual_resume_after_known_baseline_does_not_pause_again(self):
        def check(base,calls,evals):
            original=f.execution.start
            def first(*a,**kw):
                result=original(*a,**kw)
                if result['phase']=='paused':write(base/'mac/Clock_quarantine.json',{'task_committed':True,'synthetic_control_marker':True})
                return result
            with patch.object(f.execution,'start',side_effect=first):r=f.run('mac',**self.args())
            self.assertEqual(r['phase'],'paused');self.assertEqual(calls,[])
            s=read(base/'mac/checkpoint.json');s['planned_pause_done']=False;s['pause_reason']='local_clock_gap_after_settled_task';write(base/'mac/checkpoint.json',s)
            r=f.run('mac',resume=True,**self.args());self.assertEqual(r['phase'],'completed')
            self.assertEqual(calls,list(f.ROLES[1:]));self.assertEqual(len(evals),3)
            self.assertEqual(read(base/'mac/Summary.json')['checkpoint_pause_kind'],'explicit_resume_after_settled_baseline')
        self.fixture(check)

    def test_explicit_user_pause_is_never_treated_as_planned_pause(self):
        def check(base,calls,evals):
            original=f.prepare
            def prepared(*a,**kw):
                d=original(*a,**kw);f.execution.stop(d,adapter=f.Adapter());return d
            with patch.object(f,'prepare',side_effect=prepared):r=f.run('mac',**self.args())
            self.assertEqual(r['phase'],'paused');self.assertEqual(calls,[]);self.assertEqual(evals,[])
            self.assertEqual(read(base/'mac/checkpoint.json')['pause_reason'],'user_control')
        self.fixture(check)

    def test_cluster_replay_forbids_api_flags_and_login_node(self):
        def check(base,calls,evals):
            with self.assertRaises(PermissionError):f.run('cluster',**self.args())
            with patch.object(f.socket,'gethostname',return_value='master'),self.assertRaises(PermissionError):
                f.run('cluster',resume=True,allow_evaluation=True,approve_solves=12)
            self.assertFalse((base/'cluster').exists());self.assertEqual(calls,[])
        self.fixture(check)

    def test_tampered_mac_export_is_not_replayed(self):
        def check(base,calls,evals):
            f.run('mac',**self.args());e=read(base/'mac/export.json');e['checkpoint']['cursor']=0;write(base/'bad.json',e)
            with self.assertRaises(ValueError):f.accept_mac_export(base/'bad.json')
            self.assertEqual(len(calls),2)
        self.fixture(check)

    def test_state_a_rejects_legacy_field_and_partial_results(self):
        with self.assertRaises(ValueError):f.u.validate('def use_heuristics(state):\n return 0 if state["committed_objective_fraction"] > 0 else 1\n',member_count=3)
        with self.assertRaises(ValueError):f.validate_result({'valid':True,'fitness':0,'instances':[]},[{'file':'one'}])
        self.assertAlmostEqual(f.state_a.score_final_cost(110,100),.1)

    def test_check_only_does_not_read_key_or_call_solver(self):
        spec=importlib.util.spec_from_file_location('flow_entry',ROOT/'tools/flow_check.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        get=os.environ.get
        def guarded(key,*args):
            if key=='LEAFAPI_API_KEY':raise AssertionError('NO KEY READ')
            return get(key,*args)
        with patch.object(os.environ,'get',side_effect=guarded),patch.object(f,'_worker',side_effect=AssertionError('NO SOLVE')), \
                patch.object(f,'StrictNonstreamTransport',side_effect=AssertionError('NO CLIENT')),patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(cli.main(['check-only']),0)

    def test_bundle_is_exact_idempotent_and_omits_runtime_secrets(self):
        spec=importlib.util.spec_from_file_location('flow_bundle',ROOT/'tools/flow_check.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        import zipfile
        with tempfile.TemporaryDirectory() as tmp,patch.object(cli,'OUTBOX',Path(tmp)):
            p=cli.bundle();before=p.read_bytes();self.assertEqual(cli.bundle().read_bytes(),before)
            with zipfile.ZipFile(p) as archive:
                names=archive.namelist();self.assertFalse(any(name.startswith(('runs/','reports/','.venv/')) for name in names))
                self.assertFalse(any(name.endswith(('.key','.env')) for name in names))


if __name__=='__main__':unittest.main()
