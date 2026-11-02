"""Targeted offline tests: native parity, budget and replay; no network."""
from pathlib import Path
import copy
from dataclasses import asdict
import json
import math
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
import numpy as np
from llm4ad.method.eoh.population import Population
from heuristic_design.problems.tsp import eoh_single as e
from heuristic_design.core import execution
from heuristic_design.core.storage import read,write,sha


class FakeEvaluationAdapter(e.Adapter):
    """Synthetic test scores, NOT TSP solves or scientific observations."""
    def validate_result(self,result,instances):
        assert isinstance(result['valid'],bool)
    def evaluate(self,directory,state,p,c):
        if c.key in state['evaluations']:return read(directory/state['evaluations'][c.key]['path']),True
        score=-1-int(c.key[:8],16)/2**32
        result=dict(valid=True,fitness=score,mock=True,instances=[dict(file=r['file'],score=score) for r in p['instances']])
        path=directory/'synthetic-test-results'/f'{c.key}.json';write(path,result)
        state['evaluations'][c.key]=dict(status='completed',path=str(path.relative_to(directory)),sha256=sha(path))
        return result,False


class OfflineTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'runs').mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(prefix='eoh-offline-test-',dir=ROOT/'runs')
        self.root=Path(self.tmp.name)
        self.config=read(ROOT/'experiments/common/configs/tsp-eoh-single.mock.json')
    def tearDown(self):self.tmp.cleanup()
    def prepare(self,name,changes=None):
        config={**copy.deepcopy(self.config),**(changes or {})};path=self.root/(name+'.json');write(path,config)
        run=self.root/name;e.prepare(run,path);return run

    def test_default_gate_and_comparison_precheck(self):
        c,data,refs,origin,binding=e.preflight(ROOT/'experiments/common/configs/tsp-eoh-single.real.pending.json')
        self.assertFalse(c['real_requests_authorized']);self.assertEqual(len(data),20)
        self.assertEqual(binding['actual_existing_slots'],253)
        target=self.root/'must-not-create'
        with self.assertRaises(PermissionError):e.prepare(target,ROOT/'experiments/common/configs/tsp-eoh-single.real.pending.json')
        self.assertFalse(target.exists())

    def test_native_register_pack_and_selection_parity(self):
        native=Population(2);saved=dict(eoh=dict(native_generation=0,population=[],next_population=[]),population=[])
        for i,score in enumerate([-1.,-2.,-1.,None,-.9,-1.3]):
            c=asdict(e.candidates.validate(e.TEMPLATE.replace('0.0',str(i+1.0)),'fixture '+str(i),'h',1))
            native.register_function(e.make_function(c,str(i),score))
            restored=e.population(saved,{'population_size':2})
            restored.register_function(e.make_function(c,str(i),score));e.save_population(saved,restored)
            self.assertEqual([e.pack(f) for f in native._population],saved['eoh']['population'])
            self.assertEqual([e.pack(f) for f in native._next_gen_pop],saved['eoh']['next_population'])
            self.assertEqual(native.generation,saved['eoh']['native_generation'])
        rng=np.random.get_state()
        try:
            np.random.seed(501);a=[native.selection().eoh_id for _ in range(20)]
            np.random.seed(501);b=[e.population(saved,{'population_size':2}).selection().eoh_id for _ in range(20)]
            self.assertEqual(a,b)
        finally:np.random.set_state(rng)

    def test_full_slot_budget_all_native_operators_and_duplicates(self):
        run=self.prepare('full',{'mock_faults':{'H-0001':'invalid','H-0002':'failure','H-0005':'duplicate'}})
        result=execution.start(run,adapter=FakeEvaluationAdapter())
        self.assertEqual(result['phase'],'completed')
        p,s=e.protocol_state(run);j=read(run/'API_attempts.json')
        self.assertEqual(len(j['api_attempts']),12);self.assertEqual(s['cursor'],12)
        self.assertEqual({t['operator'] for t in s['tasks'].values()},set(['I1',*e.OPERATORS]))
        self.assertEqual(s['tasks']['H-0005']['AST_duplicate'],True)
        self.assertEqual(s['tasks']['H-0001']['failure'],'parse_or_constraint_error')
        self.assertEqual(s['tasks']['H-0002']['failure'],'HTTP_or_transport_failure')
        self.assertEqual(s['eoh']['evaluated_samples'],10)
        self.assertTrue((run/'milestones/Q0012.json').exists())

    def test_safe_pause_resume_matches_uninterrupted_native_rng_and_parents(self):
        full=self.prepare('full');paused=self.prepare('paused',{'pause_after_tasks':5})
        execution.start(full,adapter=FakeEvaluationAdapter())
        result=execution.start(paused,adapter=FakeEvaluationAdapter());self.assertEqual(result['phase'],'paused')
        self.assertFalse((paused/'.execution.lock').exists())
        self.assertEqual(len(read(paused/'API_attempts.json')['api_attempts']),5)
        clock=(paused/'Run_clock.json').read_bytes()
        execution.start(paused,adapter=FakeEvaluationAdapter(),resume=True)
        a=read(full/'checkpoint.json');b=read(paused/'checkpoint.json')
        self.assertEqual(clock,(paused/'Run_clock.json').read_bytes());self.assertEqual(a['eoh'],b['eoh'])
        self.assertEqual([(t['parents'],t['operator']) for t in a['tasks'].values()],[(t['parents'],t['operator']) for t in b['tasks'].values()])
        self.assertEqual(len(read(paused/'API_attempts.json')['api_attempts']),12)

    def test_consecutive_transport_failures_pause_without_refill(self):
        run=self.prepare('circuit',{'mock_faults':{f'H-{i:04d}':'failure' for i in range(3)}})
        result=execution.start(run,adapter=FakeEvaluationAdapter())
        self.assertEqual(result['phase'],'paused');self.assertFalse((run/'Stop.json').exists())
        self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),3)
        execution.start(run,adapter=FakeEvaluationAdapter(),resume=True)
        self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),12)

    def test_unknown_reservation_cannot_resume_or_send(self):
        run=self.prepare('unknown',{'pause_after_tasks':3});execution.start(run,adapter=FakeEvaluationAdapter())
        s=read(run/'checkpoint.json');s['tasks']['unknown']=dict(status='reserved');write(run/'checkpoint.json',s)
        with self.assertRaises(ValueError):execution.start(run,adapter=FakeEvaluationAdapter(),resume=True)
        self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),3)

    def test_initialization_insufficient_stops_without_manual_h(self):
        run=self.prepare('insufficient',{'mock_faults':{f'H-{i:04d}':'invalid' for i in range(8)}})
        result=execution.start(run,adapter=FakeEvaluationAdapter())
        self.assertEqual(result['phase'],'initialization_incomplete')
        self.assertEqual(len(read(run/'API_attempts.json')['api_attempts']),8)

    def test_native_replacement_does_not_require_distinct_parent_scores(self):
        run=self.prepare('score-tie',{'mock_faults':{'H-0001':'duplicate'}})
        result=execution.start(run,adapter=FakeEvaluationAdapter())
        self.assertEqual(result['phase'],'completed')
        s=read(run/'checkpoint.json')
        self.assertEqual(s['tasks']['H-0002']['parents'],['H-0000','H-0000'])

    def test_unknown_task_plan_change_rejected(self):
        run=self.prepare('tampered');plan=read(run/'Tasks.json');plan[0]['id']='changed';write(run/'Tasks.json',plan)
        with self.assertRaises(ValueError):execution.start(run,adapter=FakeEvaluationAdapter())
        self.assertFalse((run/'API_attempts.json').exists())

    def test_pair_comparison_formula_using_existing_results_only(self):
        from heuristic_design.problems.tsp.eoh_reporting import paired_rows,load_previous
        c=e.settings(ROOT/'experiments/common/configs/tsp-eoh-single.real.pending.json')
        _,_,fixed,fe,_=load_previous(Path(c['comparison_fixed_run']))
        _,_,usage,ue,_=load_previous(Path(c['comparison_u_run']))
        fixed_best=sorted((t for t in fixed if t['valid']),key=lambda t:(-t['fitness'],t['id']))[0]
        u_best=sorted((t for t in usage if t['valid']),key=lambda t:(-t['fitness'],t['id']))[0]
        values=paired_rows(fe[fixed_best['candidate']['key']]['instances'],ue[u_best['candidate']['key']]['instances'])
        self.assertEqual(sum(v['result']=='负' for v in values),1)
        self.assertEqual(sum(v['result']=='平' for v in values),19)
        self.assertAlmostEqual(sum(v['delta_fitness'] for v in values)/20,fixed_best['fitness']-u_best['fitness'],places=13)


if __name__=='__main__':unittest.main(verbosity=2)
