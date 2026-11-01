"""Bounded H10 construction + reports and handoff, no model/network requests."""
from contextlib import redirect_stdout,redirect_stderr
from io import StringIO
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from heuristic_design.core import execution,evolution_v1 as e
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core.terminal_ops import settings as u_settings
from heuristic_design.problems.tsp import h_build as h,reporting as r
from experiments.common.run_tsp_routing import preflight as u_preflight

ROOT=Path(__file__).resolve().parents[1]
MOCK=ROOT/'experiments/common/configs/tsp-h10.mock.json'
REAL=ROOT/'experiments/common/configs/tsp-h10.real.pending.json'


class Tests(unittest.TestCase):
    def setUp(self):
        (ROOT/'runs').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='test-h10-',dir=ROOT/'runs')
        self.base=Path(self.temp.name)
        self.stdout=redirect_stdout(StringIO());self.stdout.__enter__()
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK'));self.network.start()
    def tearDown(self):
        self.network.stop();self.stdout.__exit__(None,None,None);self.temp.cleanup()
    def config(self,**updates):
        c=read(MOCK);c['data_manifest']=str(ROOT/'experiments/common/fixtures/tsp-development-manifest.json')
        c.update(updates);path=self.base/f'config-{len(list(self.base.glob("config*")))}.json';write(path,c);return path
    def build(self,**updates):
        folder=self.base/f'build-{len(list(self.base.glob("build*")))}'
        h.prepare(folder,self.config(**updates));execution.start(folder,adapter=h.Adapter());return folder

    def test_real_gate_budget_and_prompt_are_explicit(self):
        c,data,refs,_=h.preflight(REAL)
        self.assertFalse(c['real_requests_authorized']);self.assertEqual(len(data),20)
        self.assertEqual(c['candidate_cap'],40)
        folder=self.base/'blocked'
        with self.assertRaises(PermissionError):h.prepare(folder,REAL)
        self.assertFalse(folder.exists())
        with self.assertRaises(PermissionError):h.prepare(folder,REAL,approve_budget=1000)
        self.assertFalse(folder.exists())
        with patch.dict('os.environ',{},clear=True),self.assertRaises(ValueError):h.prepare(folder,REAL,approve_budget=40)
        self.assertFalse(folder.exists())
        for text in ('independently','sqrt(2)','ENTIRE','No parent','priority(','No imports'):
            self.assertIn(text,h.prompt())
        bad=self.config(per_candidate_attempt_cap=2)
        with self.assertRaises(ValueError):h.preflight(bad)

    def test_complete_mock_freeze_and_handoff_parity_reports(self):
        folder=self.build();frozen=h.check_frozen(folder/'H_frozen.json')
        self.assertEqual(len(frozen['members']),10);self.assertTrue(frozen['engineering_only'])
        self.assertFalse(frozen['human_reviewed']);self.assertEqual(len(set(x['key'] for x in frozen['members'])),10)
        self.assertTrue(all(x['parents']==[] and x['operator']=='I1' for x in frozen['lineage']))
        with self.assertRaises(ValueError):h.check_frozen(folder/'H_frozen.json',real=True)
        old=sha(folder/'H_frozen.json');self.assertEqual(h.freeze(folder)['status'],'frozen')
        self.assertEqual(sha(folder/'H_frozen.json'),old)
        # All 10 constant policies, not an API search, on a tiny engineering instance.
        singles=folder/'singles';c=u_settings(folder/'next/singles.fixed.json');e.prepare(singles,c)
        self.assertEqual(e.run(singles)['phase'],'completed')
        cp,cs=e.check(singles)
        for task in cs['tasks'].values():
            member=int(task['candidate']['code'].split('return ')[1].strip())
            self.assertEqual(task['fitness'],frozen['lineage'][member]['fitness'])
        u=folder/'u';c=u_settings(folder/'next/u-mock-solve.json');e.prepare(u,c)
        r.initialize_u_analysis(u)
        self.assertEqual(e.run(u,on_progress=r.u_snapshot)['phase'],'completed')
        result=r.report(u,baseline=singles,plots=False)
        summary=read(u/'analysis/summary.json')
        self.assertEqual(summary['baseline']['status'],'compatible');self.assertTrue(summary['engineering_only'])
        self.assertEqual(summary['real_API_attempts'],0)
        self.assertTrue((u/'analysis/champion.py').exists())
        self.assertEqual(len(read(u/'analysis/plot-data.json')['generations']),1)
        r.report(folder,plots=False)
        self.assertEqual(read(folder/'analysis/summary.json')['valid_unique_candidates'],12)
        # Same score vectors are retained as distinct code, not silently removed.
        self.assertEqual(len(h.pool(folder,*h.protocol_state(folder))),12)

    def test_pause_resume_preserves_attempts_and_original_budget(self):
        folder=self.build(pause_after_tasks=4)
        p,s=h.protocol_state(folder);self.assertEqual(s['phase'],'paused');self.assertEqual(s['cursor'],4)
        self.assertFalse((folder/'H_frozen.json').exists());self.assertFalse((folder/'.execution.lock').exists())
        journal=read(folder/'API_attempts.json');before=set(journal['api_attempts'])
        identity=s['identity'];self.assertEqual(len(before),4)
        r.report(folder,plots=False);summary=read(folder/'analysis/summary.json')
        self.assertEqual(summary['committed_tasks'],4);self.assertIn('进行中',summary['status'])
        self.assertEqual(summary['pause_records'],1)
        execution.start(folder,adapter=h.Adapter(),resume=True)
        p,s=h.protocol_state(folder);self.assertEqual(s['identity'],identity)
        self.assertEqual(s['phase'],'completed');self.assertEqual(s['cursor'],12)
        self.assertEqual(len(read(folder/'API_attempts.json')['api_attempts']),12)
        self.assertTrue(before<=set(read(folder/'API_attempts.json')['api_attempts']))
        self.assertEqual(read(folder/'milestones/Q0004.json')['cursor'],4)
        self.assertEqual(read(folder/'milestones/Q0012.json')['cursor'],12)

    def test_failure_duplicate_invalid_and_no_manual_refill(self):
        folder=self.build(mock_faults={'H-0001':'duplicate','H-0002':'invalid',
                      'H-0003':'invalid_evaluation','H-0004':'failure'})
        p,s=h.protocol_state(folder);self.assertEqual(s['phase'],'completed');self.assertEqual(s['cursor'],12)
        self.assertEqual(len(read(folder/'API_attempts.json')['api_attempts']),12)
        self.assertTrue(s['tasks']['H-0001']['AST_duplicate']);self.assertTrue(s['tasks']['H-0001']['cache_hit'])
        self.assertEqual(s['tasks']['H-0002']['failure'],'parse_or_constraint_error')
        self.assertEqual(s['tasks']['H-0003']['failure'],'evaluation_invalid')
        self.assertEqual(s['tasks']['H-0004']['failure'],'HTTP_or_transport_failure')
        self.assertFalse((folder/'H_frozen.json').exists())
        self.assertEqual(read(folder/'H_build_outcome.json')['status'],'insufficient_valid_unique_H')
        r.report(folder,plots=False);summary=read(folder/'analysis/summary.json')
        self.assertEqual(summary['duplicates'],1);self.assertEqual(summary['valid_unique_candidates'],8)
        self.assertEqual(summary['failures'],3)

    def test_unknown_reservation_never_replayed_and_inflight_not_reported(self):
        folder=self.base/'unknown';h.prepare(folder,self.config())
        s=read(folder/'checkpoint.json');s['tasks']['H-0000']={'id':'H-0000','status':'reserved','valid':False}
        s['phase']='paused';write(folder/'checkpoint.json',s)
        with patch.object(h.MockTransport,'dispatch',side_effect=AssertionError('NO REPLAY')):
            with self.assertRaisesRegex(ValueError,'uncommitted'):execution.start(folder,adapter=h.Adapter(),resume=True)
        r.report(folder,plots=False)
        self.assertEqual(read(folder/'analysis/summary.json')['committed_tasks'],0)
        self.assertEqual(read(folder/'analysis/plot-data.json')['curve'],[])

    def test_three_transport_failures_stop_without_refill(self):
        folder=self.build(mock_faults={f'H-{i:04d}':'failure' for i in range(3)})
        p,s=h.protocol_state(folder);self.assertEqual(s['phase'],'stopped')
        self.assertEqual(len(read(folder/'API_attempts.json')['api_attempts']),3)
        self.assertTrue((folder/'.execution.lock').exists());self.assertFalse((folder/'H_frozen.json').exists())
        with self.assertRaises(ValueError):execution.start(folder,adapter=h.Adapter(),resume=True)

    def test_hard_auth_failure_is_charged_and_never_retried(self):
        class Denied(h.MockTransport):
            def dispatch(self,key,text,*,kind,on_sent):
                on_sent();exc=RuntimeError('unit fixture unauthorized')
                exc.metadata={'http_status':401};raise exc
        original=h.Adapter.transport
        def denied(adapter,p):return Denied(adapter.client_config(p),{})
        with patch.object(h.Adapter,'transport',denied):folder=self.build()
        p,s=h.protocol_state(folder)
        self.assertEqual(s['phase'],'stopped');self.assertEqual(s['cursor'],0)
        journal=read(folder/'API_attempts.json')
        self.assertEqual(len(journal['api_attempts']),1);self.assertTrue(journal['halt_reason'])
        r.report(folder,plots=False);summary=read(folder/'analysis/summary.json')
        self.assertEqual(summary['transport_failed_attempts'],1)
        self.assertEqual(summary['uncommitted_reserved_attempts'],1)

    def test_live_u_report_excludes_reserved_tasks_and_rejects_incompatible_baseline(self):
        from copy import deepcopy
        c={'problem':'tsp','population_size':2,'generations':1,'generation_request_cap':4}
        folder=self.base/'live-u';e.prepare(folder,c)
        p,s=e.check(folder);s['phase']='running';s['initialization_requests']=1
        s['tasks']['INIT-0000']={'id':'INIT-0000','stage':'initialization','generation':0,
            'operator':'INIT','request_key':'unknown','status':'request_reserved','valid':False,'parents':[]}
        e.save(folder,s);r.report(folder,plots=False)
        summary=read(folder/'analysis/summary.json')
        self.assertEqual(summary['committed_tasks'],0);self.assertEqual(summary['reserved_attempts'],1)
        self.assertIn('进行中',summary['status'])
        self.assertEqual(read(folder/'analysis/plot-data.json')['curve'],[])
        b=deepcopy(p);b['members'].reverse()
        self.assertIn('members',r.compatibility(p,b))
        b=deepcopy(p);b['config']['solve_seed']=502
        self.assertIn('config.solve_seed',r.compatibility(p,b))

    def test_report_failure_never_changes_scientific_receipts(self):
        folder=self.build()
        before={str(p.relative_to(folder)):sha(p) for p in folder.rglob('*.json') if 'analysis' not in p.parts}
        with patch.object(r,'report',side_effect=RuntimeError('render fixture failure')),redirect_stderr(StringIO()):
            self.assertFalse(r.safe_report(folder))
        for name,value in before.items():self.assertEqual(sha(folder/name),value)
        r.report(folder,plots=False)
        self.assertEqual(read(folder/'analysis/summary.json')['phase'],'completed')

    def test_u_nodes_report_actual_overshoot_and_callback_failure_is_nonfatal(self):
        folder=self.base/'nodes';folder.mkdir()
        state={'initialization_requests':5,'generation_requests':46,'generation':4,'population':[],
               'identity':'test','completed_tasks':51}
        r.u_snapshot(folder,state,{'config':{'api_attempt_cap':220}})
        value=read(folder/'budget-nodes/Q0050.json')
        self.assertEqual(value['target_requests'],50);self.assertEqual(value['observed_reserved_requests'],51)
        e._notify_progress(lambda *a:(_ for _ in ()).throw(RuntimeError('plot-only failure')),folder,{'completed_tasks':51},{})
        self.assertTrue(read(folder/'Snapshot_error.json')['raw_results_preserved'])


if __name__=='__main__':unittest.main()
