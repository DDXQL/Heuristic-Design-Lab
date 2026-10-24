"""Only isolated toy spaces, synthetic results and in-memory toy schedules.

NEVER sample the formal865 space or read a generated A4 ticket's real score.
"""
from copy import deepcopy
import importlib
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.a4_static.model import canonical,decode,ticket,policy,output,validate
from fjsp_usage.a4_static.engine import Campaign,read,write,sha,sample_indices,validate_result
from fjsp_usage.a4_static.authorization import require_approval
from fjsp_usage.usage_v2.execution import decode_output,combine_scores,construct_usage_schedule,NormalizationError
from fjsp_usage.fusion_v2.execution import construct_fusion_schedule,v1_adapter
from fjsp_usage.research.candidates import validate_code,H_ARGS
from tools import a4_static_experiment as a
from tools.a4_static_report import report
from tests.test_baseline_a import toy

RECEIPTS=[]


def toy_protocol():
    return {'mode':'synthetic','space_size':7,'queries_per_repeat':3,'search_seeds':[11,22],
        'instances':[{'file':'SYNTHETIC-A','LB':2.},{'file':'SYNTHETIC-B','LB':3.}],
        'new_evaluation_cap':12,'new_solve_pass_cap':24}


def synthetic_result(index,invalid=False):
    rows=[{'file':'SYNTHETIC-A','makespan':4+index,'lower_bound':2.,'score':-(4+index)/2.,'feasible':True},
          {'file':'SYNTHETIC-B','makespan':6+index,'lower_bound':3.,'score':-(6+index)/3.,'feasible':True}]
    return {'valid':not invalid,'total_instances':2,'fitness':None if invalid else sum(r['score'] for r in rows)/2,
            'instances':rows[:1] if invalid else rows,'error_type':'Timeout' if invalid else None}


class A4Tests(unittest.TestCase):
    def test_canonical_endpoints_repeated_members_direction_and_bounds(self):
        self.assertEqual(10+45*19,865)
        self.assertEqual(canonical((2,7),(20,0)),{'kind':'single','member':2})
        self.assertEqual(canonical((2,7),(0,20)),{'kind':'single','member':7})
        self.assertEqual(canonical((2,2),(3,17)),{'kind':'single','member':2})
        self.assertEqual(canonical((7,2),(3,17)),{'kind':'pair','i':2,'j':7,'k':17})
        for spec in [{'kind':'single','member':3},{'kind':'pair','i':2,'j':7,'k':3},{'kind':'pair','i':8,'j':9,'k':19}]:
            self.assertEqual(decode(ticket(spec)),spec)
        for spec in [{'kind':'pair','i':7,'j':2,'k':3},{'kind':'pair','i':2,'j':2,'k':3},
                     {'kind':'pair','i':2,'j':7,'k':0},{'kind':'single','member':True}]:
            with self.assertRaises(ValueError):validate(spec)
        for ticks in [(-1,21),(1,18),(True,19)]:
            with self.assertRaises(ValueError):canonical((2,7),ticks)

    def test_constant_weight_float_convention_and_no_state_dependence(self):
        spec={'kind':'pair','i':2,'j':7,'k':14};u=policy(spec);mode,vector=u()
        self.assertEqual(mode,1);self.assertEqual(vector[2],.7);self.assertEqual(vector[7],1.-.7)
        self.assertEqual(u(0,0,0,0,0,0,-1),u(1,99,2,3,4,5,9))
        self.assertNotEqual(vector[7],.3) # Never silently merge approximate raw float vectors.
        decoded=decode_output((1,(1e-16,1.)+(0.,)*8),10)
        self.assertEqual(decoded['support'],(0,1)) # No epsilon pruning.
        with self.assertRaises(NormalizationError):decode_output((1,(1e-323,1e100)+(0.,)*8),10)

    def test_toy_V1_and_frozen_fusion_compatibility(self):
        rules=[lambda p,w,n,j,m,s,f:-f,lambda p,w,n,j,m,s,f:w-p]+[lambda *x:0.]*8
        for spec in [{'kind':'single','member':0}]+[{'kind':'pair','i':0,'j':1,'k':k} for k in (1,7,10,19)]:
            native=construct_usage_schedule(toy(),rules,policy(spec))
            adapter=construct_fusion_schedule(toy(),rules,v1_adapter(policy(spec)))
            self.assertEqual(native.schedule,adapter.schedule);self.assertEqual(native.score,adapter.score)
            self.assertEqual(adapter,construct_fusion_schedule(toy(),rules,v1_adapter(policy(spec))))
        columns={0:(4.,4.),1:(3.,3.)}
        self.assertEqual(combine_scores(columns,(.5,.5),(0,1))[0],(0.,0.))

    def test_blind_sampler_on_isolated_toy_space_only(self):
        self.assertEqual(sample_indices(7,3,11),sample_indices(7,3,11))
        self.assertEqual(len(set(sample_indices(7,3,11))),3)
        with self.assertRaises(ValueError):sample_indices(7,8,11)
        with self.assertRaises(ValueError):sample_indices(7,3,True)
        # No call with865; no cache object or Fitness argument exists in the sampler.

    def make(self,path):
        p=toy_protocol();plans=[sample_indices(7,3,s) for s in p['search_seeds']]
        return Campaign.create(path,p,plans)

    def test_durable_resume_cache_billing_and_finished_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.make(Path(tmp)/'toy');calls=[];memo={}
            def evaluate(index,folder,reserve):
                calls.append(index)
                if index in memo:return memo[index],'campaign_cache',{'synthetic':True}
                if index==0:
                    value=synthetic_result(index);memo[index]=value
                    return value,'historical_cache',{'synthetic':True}
                reserve();value=synthetic_result(index);memo[index]=value
                return value,'new',{'synthetic':True}
            c.execute(evaluate,limit=1);c.execute(evaluate)
            before=len(calls);c.execute(evaluate);self.assertEqual(len(calls),before)
            p,plans,state,flat=c.validate();self.assertEqual(len(state['queries']),6)
            self.assertEqual(sum(q['logical_evaluations'] for q in state['queries']),12)
            self.assertTrue(any(q['origin']=='campaign_cache' for q in state['queries']))
            summary=report(c.directory,Path(tmp)/'report');self.assertEqual(summary['mode'],'synthetic')
            self.assertEqual(summary['completed_repeats'],2);self.assertEqual(summary['within_repeat_duplicate_queries'],0)
            RECEIPTS.append({'mock':'synthetic7-policy/2-repeat campaign','summary':summary,'formal_space_sampled':False})

    def test_failures_consume_slots_and_never_prefix_fitness(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.make(Path(tmp)/'toy')
            def evaluate(index,folder,reserve):reserve();return synthetic_result(index,True),'new',{'synthetic':True}
            c.execute(evaluate);state=c.validate()[2]
            self.assertEqual(len(state['queries']),6)
            self.assertTrue(all(read(c.directory/q['result_path'])['fitness'] is None for q in state['queries']))
        invalid=synthetic_result(1,True);invalid['fitness']=-2.
        with self.assertRaises(ValueError):validate_result(invalid,toy_protocol()['instances'])

    def test_unresolved_reservation_and_corruption_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.make(Path(tmp)/'toy')
            def crash(index,folder,reserve):reserve();raise RuntimeError('synthetic interrupted worker')
            with self.assertRaises(RuntimeError):c.execute(crash)
            self.assertTrue((c.directory/'Stop.json').exists())
            with self.assertRaises(ValueError):c.execute(lambda *x:self.fail('must not repeat'))
        with tempfile.TemporaryDirectory() as tmp:
            c=self.make(Path(tmp)/'toy')
            c.execute(lambda i,f,r:(synthetic_result(i),'historical_cache',{}),limit=1)
            state=read(c.directory/'checkpoint.json');write(c.directory/state['queries'][0]['result_path'],{'broken':True})
            with self.assertRaisesRegex(ValueError,'result identity'):c.validate()

    def test_wall_stop_cannot_reset_allowance(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.make(Path(tmp)/'toy');calls=[]
            c.execute(lambda *x:calls.append(x),clock=lambda:100.,wall_deadline=200.)
            self.assertEqual(c.validate()[2]['phase'],'wall_budget_stopped');self.assertEqual(calls,[])
            c.execute(lambda *x:calls.append(x),clock=lambda:0.,wall_deadline=99999.)
            self.assertEqual(calls,[])
        with tempfile.TemporaryDirectory() as tmp:
            c=self.make(Path(tmp)/'toy');write(c.directory/'Run_clock.json',{'start':1,'end':2})
            state=read(c.directory/'checkpoint.json');state['run_clock_sha256']=sha(c.directory/'Run_clock.json');write(c.directory/'checkpoint.json',state)
            c.validate();write(c.directory/'Run_clock.json',{'start':1,'end':999})
            with self.assertRaisesRegex(ValueError,'clock identity'):c.validate()

    def test_false_approval_cannot_draw_formal_candidates_or_create_run(self):
        with self.assertRaises(PermissionError):require_approval({'approved':False})
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'not-approved.json';write(f,{'approved':False})
            with patch.object(a,'sample_indices',side_effect=AssertionError('formal sampling forbidden')):
                with self.assertRaises(PermissionError):a.prepare(a.DEFAULT,f)
        self.assertFalse(a.DEFAULT.exists())

    def test_real_spawn_A4_worker_on_in_memory_toy_only(self):
        sources=dict(a.read(a.s.DEFAULT/'Protocol.json')['source_files'])
        for name in a.MODULES:
            path=Path(importlib.import_module(name).__file__).resolve();sources[str(path.relative_to(a.ROOT))]=sha(path)
        p={'source_files':sources,'instances':[{'relative_path':'inputs/train/TOY.fjsp'}]}
        identity=a.witness(p)['identity']
        with patch.object(Campaign,'execute',lambda *x:None):
            with self.assertRaisesRegex(ValueError,'loaded method mismatch'):a.witness(p)
        members=tuple(validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -earliest_finish\n',kind='h') for _ in range(10))
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);folder=d/'toy-evidence';folder.mkdir()
            rows,failure,life=a.collect(mp.get_context('spawn'),a.worker,{'directory':str(d),'folder':str(folder),'protocol':p,
                'spec':{'kind':'pair','i':2,'j':7,'k':3}},members,(toy(),),('TOY.fjsp',),30,None,lambda x:write(folder/'lifecycle.json',x))
            self.assertIsNone(failure);self.assertEqual(life['exitcode'],0);self.assertTrue(life['receiver_thread_stopped'])
            self.assertEqual(read(folder/'before.json')['identity'],identity);self.assertEqual(read(folder/'after.json')['identity'],identity)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['captured_solves'],2)
            RECEIPTS.append({'mock':'real process, synthetic H and in-memory toy, no raw train open','lifecycle':life,'identity':identity})


def acceptance():
    out=a.AUDIT;out.mkdir(exist_ok=True)
    if (out/'Synthetic_acceptance.json').exists():raise ValueError('acceptance file exists, preserve evidence')
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(A4Tests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    paths={str(Path(importlib.import_module(n).__file__).resolve().relative_to(a.ROOT)) for n in a.MODULES}
    paths.update(('tools/a4_static_audit.py','tests/test_a4_static.py','experiments/tier2/a4_static/run.py',
                  'docs/TIER2_A4_STATIC_SEARCH_PROTOCOL_V1.md','docs/STATIC_BASELINE_SCOPE_ADDENDUM_V2.md'))
    receipt={'passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'files':{n:sha(a.ROOT/n) for n in sorted(paths)},'receipts':RECEIPTS,
        'formal_A4_plans_drawn':0,'formal_train_solves':0,'real_API_calls':0,
        'scope':'toy-index7 samples/synthetic results/in-memory toy only; future formal prepare explicitly denied by false authorization test'}
    write(out/'Synthetic_acceptance.json',receipt)
    if not receipt['passed']:raise ValueError('synthetic gate failed')


if __name__=='__main__':acceptance()
