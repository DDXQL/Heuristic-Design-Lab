"""Focused saved-data/Mock checks: ZERO external API and ZERO strategy solves."""
from pathlib import Path
import copy,io,json,tempfile,unittest,sys
from contextlib import redirect_stdout
from dataclasses import asdict
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.problems.fjsp import eoh_single as e
from heuristic_design.core import execution
from heuristic_design.core.storage import read,write,sha

class Checks(unittest.TestCase):
    def setUp(self):
        (ROOT/'runs').mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(prefix='fjsp-eoh-offline-',dir=ROOT/'runs');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.c=read(ROOT/'experiments/common/configs/fjsp-eoh-single.mock.json')
        self.stack=__import__('contextlib').ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')))
        self.stack.enter_context(patch('heuristic_design.problems.tsp.h_build.evaluate_task',side_effect=AssertionError('NO POLICY SOLVES')))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
    def prepare(self,name,changes=None):
        cfg={**self.c,**(changes or {})};path=self.root/(name+'.json');write(path,cfg)
        run=self.root/name;e.prepare(run,path);return run
    def execute(self,run,resume=False):return execution.start(run,adapter=e.Adapter(),resume=resume)
    def test_pending_real_check_and_closed_launch_zero_side_effects(self):
        c,data,refs,origin,binding=e.preflight(ROOT/'experiments/common/configs/fjsp-eoh-single.real.pending.json')
        self.assertEqual(len(data),21);self.assertEqual(c['api_attempt_cap'],1050);self.assertEqual(c['initialization_request_cap'],50)
        self.assertEqual(c['initialization_sample_cap'],10);self.assertEqual(e.transport_status(c),'pending_external_API_reliability_conclusion')
        with self.assertRaises(PermissionError):e.prepare(self.root/'paid',ROOT/'experiments/common/configs/fjsp-eoh-single.real.pending.json',allow_api=True,approve_budget=1050)
        self.assertFalse((self.root/'paid').exists())
    def test_config_rejects_unused_fields_bad_caps_and_real_Mock_scores(self):
        for change in ({'unknown':1},{'api_attempt_cap':1051,'candidate_cap':1051},{'initialization_request_cap':51},
                       {'per_candidate_attempt_cap':2},{'api_mode':'real','evaluation_mode':'mock'},{'pause_after_tasks':True}):
            path=self.root/'bad.json';write(path,{**self.c,**change})
            with self.assertRaises(ValueError):e.settings(path)
    def test_same_train_order_LB_seed_timeout_required(self):
        cfg=ROOT/'experiments/common/configs/fjsp-eoh-single.real.pending.json';c,data,refs,_,_=e.preflight(cfg)
        for key,value in [('solve_seed',502),('instance_timeout_seconds',29),('expected_model','wrong-model')]:
            with self.assertRaises(ValueError):e.comparison_identity({**c,key:value},data,refs)
        with self.assertRaises(ValueError):e.comparison_identity(c,list(reversed(data)),refs)
        altered=copy.deepcopy(refs);altered[0]['reference']+=1
        with self.assertRaises(ValueError):e.comparison_identity(c,data,altered)
    def test_fixed_H_language_and_native_prompts_all_operators(self):
        a=e.Adapter();c=e.validate_code(e.TEMPLATE.replace('0.0','-earliest_finish'),kind='h')
        self.assertEqual(a.parse_candidate('{Fixed fixture.}\n```python\n'+c.code+'```',self.c).key,c.key)
        parent=dict(id='H0',candidate=asdict(c),fitness=-2.)
        for op in ['I1',*e.native.OPERATORS]:
            ps=[] if op=='I1' else [parent,parent] if op in ('E1','E2') else [parent]
            text=a.build_prompt(self.c,dict(operator=op),ps,[])
            self.assertIn('processing_time',text);self.assertIn('no local search',text)
        for code in ('def priority(distance_current, progress):\n    return 1\n', e.TEMPLATE.replace('0.0','processing_time ** 0.5')):
            with self.assertRaises(e.CandidateError):e.validate_code(code,kind='h')
    def test_all_operators_failures_duplicates_conserve_attempts(self):
        run=self.prepare('all',{'mock_faults':{'H-0001':'invalid','H-0002':'failure','H-0005':'duplicate'}})
        r=self.execute(run);self.assertEqual(r['phase'],'completed')
        p,s=e.protocol_state(run);j=read(run/'API_attempts.json')
        self.assertEqual(len(j['api_attempts']),12);self.assertEqual(s['cursor'],12)
        self.assertEqual({t['operator'] for t in s['tasks'].values()},set(['I1',*e.native.OPERATORS]))
        self.assertTrue(s['tasks']['H-0005']['AST_duplicate']);self.assertEqual(s['tasks']['H-0002']['failure'],'HTTP_or_transport_failure')
        self.assertFalse((run/'.execution.lock').exists());self.assertEqual(e.export(run)['engineering_only'],True)
        with self.assertRaises(ValueError):self.execute(run,resume=True)
    def test_pause_resume_same_rng_parents_population_and_budget(self):
        full=self.prepare('full');paused=self.prepare('paused',{'pause_after_tasks':5})
        self.execute(full);self.assertEqual(self.execute(paused)['phase'],'paused')
        clock=(paused/'Run_clock.json').read_bytes();self.assertFalse((paused/'.execution.lock').exists())
        self.execute(paused,resume=True);a=read(full/'checkpoint.json');b=read(paused/'checkpoint.json')
        self.assertEqual(a['eoh'],b['eoh']);self.assertEqual(clock,(paused/'Run_clock.json').read_bytes())
        self.assertEqual([(t['parents'],t['operator']) for t in a['tasks'].values()],[(t['parents'],t['operator']) for t in b['tasks'].values()])
        self.assertEqual(len(read(paused/'API_attempts.json')['api_attempts']),12)
    def test_initialization_cap_is_total_budget_subset_without_refill(self):
        run=self.prepare('init',{'mock_faults':{f'H-{i:04d}':'invalid' for i in range(8)}})
        self.assertEqual(self.execute(run)['phase'],'initialization_incomplete')
        self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),8)
    def test_three_transport_failures_pause_and_never_refund(self):
        run=self.prepare('temporary',{'mock_faults':{f'H-{i:04d}':'failure' for i in range(3)}})
        self.assertEqual(self.execute(run)['phase'],'paused');self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),3)
        self.execute(run,resume=True);self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),12)
    def test_unknown_reserved_task_and_changed_source_rejected(self):
        run=self.prepare('unknown',{'pause_after_tasks':3});self.execute(run)
        s=read(run/'checkpoint.json');s['tasks']['unknown']=dict(status='reserved');write(run/'checkpoint.json',s)
        with self.assertRaises(ValueError):self.execute(run,resume=True)
        self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),3)
    def test_fixed_R1_result_validation_and_host_dispatch_no_solve(self):
        cfg=ROOT/'experiments/common/configs/fjsp-eoh-single.real.pending.json';c,data,refs,_,_=e.preflight(cfg)
        r=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab/runs/b1-v6-r1-train21-20261029-221535-858514-d3145ddd')
        s=read(r/'checkpoint.json');task=s['tasks']['INIT-0000'];meta=s['evaluations'][task['candidate']['key']]
        self.assertEqual(sha(r/meta['path']),meta['sha256']);result=read(r/meta['path']);adapter=e.Adapter()
        adapter.validate_result(result,data);self.assertEqual(result['fitness'],-2.1118049606260487)
        changed=copy.deepcopy(result);changed['instances'][0]['score']+=.01
        with self.assertRaises(ValueError):adapter.validate_result(changed,data)
        p=read(Path(c['comparison_a_run'])/'Protocol.json');h=adapter.checked_candidate(p['members'][0]);state=dict(evaluations={},tasks={'FIXED_H0':dict(status='reserved')})
        protocol={**p,'config':{**p['config'],'evaluation_mode':'solve'},'members':[]}
        def replay(task,bound):
            self.assertEqual(bound['config']['problem'],'fjsp');self.assertEqual(bound['config']['instance_timeout_seconds'],30)
            self.assertEqual(len(bound['members']),1);self.assertEqual(bound['members'][0]['key'],h.key)
            self.assertEqual(task['candidate']['code'].strip(),'def use_heuristics(state):\n    return 0')
            write(self.root/'worker-receipts/FIXED_H0/result.json',result);return result
        with patch('heuristic_design.problems.tsp.h_build.evaluate_task',side_effect=replay):
            actual,cache=adapter.evaluate(self.root,state,protocol,h)
        self.assertFalse(cache);self.assertEqual(actual,result)
        cached,cache=adapter.evaluate(self.root,state,protocol,h);self.assertTrue(cache);self.assertEqual(cached,result)
    def test_mock_physical_result_separation(self):
        with self.assertRaises(ValueError):e.Adapter().validate_result(dict(valid=True,fitness=-1.,mock=True,instances=[dict(file='x',score=-1.)]),[dict(file='x')])

if __name__=='__main__':unittest.main(verbosity=2)
