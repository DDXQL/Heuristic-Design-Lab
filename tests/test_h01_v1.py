"""SYNTHETIC/MOCK ONLY. Never evaluate train21/test28 or access a provider."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from tools import h01_v1 as v
from tools import h01_v1_prepare as p


class Crash(BaseException):pass


def fixture(n=4):
    instances=[{'file':f'SYNTHETIC_{i}.fjsp','LB':1.,'sha256':'mock-only'} for i in range(n)]
    tasks=[{'id':f'{i:02d}_{role}','index':i,'role':role,'file':r['file']}
        for i,r in enumerate(instances) for role in (('dynamic','equal') if i%2==0 else ('equal','dynamic'))]
    return {'mode':'mock','version':'MOCK-V1-NEVER-RESEARCH-RESULT','instances':instances,
        'tasks':tasks,'task_cap':2*n,'statistics':p.STATISTICS}


def success(task):
    cmax=10+task['index']+(1 if task['role']=='dynamic' else 0)
    physical=[[0,0,0,0,cmax]];key=digest(physical)
    row={'file':task['file'],'makespan':cmax,'lower_bound':1.,'score':-float(cmax),'feasible':True,
        'single_solve_seconds':.01,'deterministic_recheck_seconds':.01,
        'single_h_calls':[2,2]+[0]*8,'deterministic_recheck_h_calls':[2,2]+[0]*8,
        'physical_schedule':physical,'physical_schedule_sha256':key,'recheck_physical_schedule_sha256':key}
    return {'valid':True,'fitness':row['score'],'instances':[row],'total_instances':1,'primary_evaluation_seconds':.02}


def failure(task):
    return {'valid':False,'fitness':None,'instances':[],'total_instances':1,
        'failed_instance':task['file'],'error_type':'Timeout','primary_evaluation_seconds':None}


class V1MockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.protocol=fixture();self.calls=[]
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name in ('socket.socket.connect','tools.h01_weight_search.evaluate_weight',
                     'fjsp_usage.research_real.runtime.evaluate',
                     'fjsp_usage.research_real.workflow.Workflow.select',
                     'fjsp_usage.usage_v2.execution.construct_usage_schedule',
                     'fjsp_usage.research_real.leafapi.query_status',
                     'fjsp_usage.usage_v2.billing.query_invoices',
                     'fjsp_usage.research_real.staged_evaluation.StagedDataset.load'):
            self.stack.enter_context(patch(name,side_effect=AssertionError('MOCK: no network or FJSP evaluation')))

    def run_object(self):return v.PairRun(self.root,self.protocol,'MOCK-IDENTITY',lambda:None)

    def evaluate(self,task):self.calls.append(task['id']);return success(task)

    def test_fixed_order_completion_and_completed_restart_no_repeat(self):
        run=self.run_object();run.run(self.evaluate)
        self.assertEqual(self.calls,[t['id'] for t in self.protocol['tasks']])
        self.assertEqual([t['role'] for t in self.protocol['tasks']][:4],['dynamic','equal','equal','dynamic'])
        self.run_object().run(self.evaluate);self.assertEqual(len(self.calls),8)
        report=v.report(self.root,self.protocol,'MOCK-IDENTITY')
        self.assertEqual(report['mode'],'mock');self.assertEqual(report['statistics']['delta_fitness'],-1.)
        self.assertEqual(report['reserved_evaluations'],8)

    def test_failure_continues_fixed_tasks_full_fitness_and_statistics_null(self):
        def evaluate(t):self.calls.append(t['id']);return failure(t) if t['id']=='00_dynamic' else success(t)
        self.run_object().run(evaluate);r=v.report(self.root,self.protocol,'MOCK-IDENTITY')
        self.assertEqual(len(self.calls),8);self.assertIsNone(r['fitness']['dynamic'])
        self.assertIsNotNone(r['fitness']['equal']);self.assertIsNone(r['statistics']['delta_fitness'])
        self.assertEqual(r['pair_outcomes']['unknown'],1)

    def test_reserved_unknown_is_invalid_never_repeated_after_restart(self):
        def crash(t):self.calls.append(t['id']);raise Crash()
        with self.assertRaises(Crash):self.run_object().run(crash)
        self.run_object().run(self.evaluate)
        self.assertEqual(self.calls.count('00_dynamic'),1)
        s=p.read(self.root/'checkpoint.json');self.assertEqual(s['tasks']['00_dynamic']['status'],'interrupted')
        r=v.report(self.root,self.protocol,'MOCK-IDENTITY');self.assertIsNone(r['statistics']['delta_fitness'])

    def test_saved_complete_result_before_checkpoint_commit_recovered(self):
        run=self.run_object();native=run.save
        def save():
            if any(t['status']=='completed' for t in run.state['tasks'].values()):raise Crash()
            native()
        run.save=save
        with self.assertRaises(Crash):run.run(self.evaluate)
        self.run_object().run(self.evaluate)
        self.assertEqual(self.calls.count('00_dynamic'),1)
        self.assertEqual(len(self.calls),8)

    def test_orphan_result_and_corrupt_checkpoint_no_reset(self):
        (self.root/'results').mkdir();atomic_json(self.root/'results/00_dynamic.json',{})
        with self.assertRaisesRegex(ValueError,'orphan'):self.run_object()
        (self.root/'results/00_dynamic.json').unlink()
        atomic_json(self.root/'checkpoint.json',{'identity':'OTHER','mode':'mock','tasks':{}})
        with self.assertRaisesRegex(ValueError,'another protocol'):self.run_object()

    def test_corrupt_completed_result_stops_without_reevaluation(self):
        self.run_object().run(self.evaluate)
        path=self.root/'results/00_dynamic.json';d=p.read(path);d['result']['fitness']=123;atomic_json(path,d)
        with self.assertRaises(ValueError):self.run_object().run(self.evaluate)
        self.assertEqual(len(self.calls),8)

    def test_task_cap_and_foreign_result_no_extra_evaluations(self):
        self.run_object().run(self.evaluate)
        path=self.root/'checkpoint.json';d=p.read(path);d['tasks']['99_dynamic']={'status':'reserved'};atomic_json(path,d)
        with self.assertRaises(ValueError):self.run_object()
        self.assertEqual(len(self.calls),8)

    def test_verifier_gate_before_reservation(self):
        def reject():raise ValueError('frozen source changed')
        run=v.PairRun(self.root,self.protocol,'MOCK-IDENTITY',reject)
        with self.assertRaises(ValueError):run.run(self.evaluate)
        self.assertFalse((self.root/'checkpoint.json').exists());self.assertFalse(self.calls)

    def test_unauthorized_run_no_loader_or_evaluator(self):
        protocol={**self.protocol,'gates':{'history_blocks_execution':False,'duplicate_blocks_execution':False}}
        with patch.object(v,'check',return_value=(protocol,'MOCK-IDENTITY')):
            with self.assertRaisesRegex(ValueError,'not authorized'):v.real_run(self.root)
        self.assertFalse((self.root/'checkpoint.json').exists())

    def test_authorization_scope_exact_and_history_not_overrideable(self):
        protocol={**self.protocol,'gates':{'history_blocks_execution':False,'duplicate_blocks_execution':False}}
        auth={'stage':'V1-1','approved':True,'person':'DDXQL','protocol_sha256':'MOCK-IDENTITY',
            'no_known_unrecorded_test28_use':True,'accept_reserved_test28_consumption':True}
        atomic_json(self.root/'V1_1_authorization.json',{**auth,'approved':1})
        with patch.object(v,'check',return_value=(protocol,'MOCK-IDENTITY')):
            with self.assertRaises(ValueError):v.require_execution(self.root)
            atomic_json(self.root/'V1_1_authorization.json',auth);v.require_execution(self.root)
            protocol['gates']['history_blocks_execution']=True
            with self.assertRaises(ValueError):v.require_execution(self.root)

    def test_foreign_h_wrong_LB_and_recheck_mismatch_rejected(self):
        t=self.protocol['tasks'][0]
        for field in ('LB','h','recheck','physical','time'):
            d=success(t);row=d['instances'][0]
            if field=='LB':row['lower_bound']=2.
            elif field=='h':row['single_h_calls'][3]=1
            elif field=='recheck':row['recheck_physical_schedule_sha256']='different'
            elif field=='physical':row['physical_schedule'][0][-1]=99
            else:row['single_solve_seconds']=float('nan')
            with self.subTest(field=field),self.assertRaises(ValueError):v.validate_result(d,self.protocol['instances'][0])

    def test_batch_modes_and_tasks_cannot_be_confused(self):
        self.run_object().run(self.evaluate)
        with self.assertRaises(ValueError):v.PairRun(self.root,{**self.protocol,'mode':'real'},'MOCK-IDENTITY',lambda:None)
        other=deepcopy(self.protocol);other['tasks'][1]=other['tasks'][0]
        with self.assertRaises(ValueError):v.PairRun(self.root,other,'MOCK-IDENTITY',lambda:None)

    def test_incomplete_report_never_computes_complete_case_statistic(self):
        r=v.report(self.root,self.protocol,'MOCK-IDENTITY')
        self.assertEqual(r['phase'],'not_started');self.assertIsNone(r['statistics']['delta_fitness'])
        self.assertFalse((self.root/'checkpoint.json').exists())

    def test_metadata_structure_only_and_header_job_relabel_duplicates(self):
        a=self.root/'SYNTHETIC_A.fjsp';b=self.root/'SYNTHETIC_B.fjsp'
        head='NAME: {name}\nTYPE: FJSP\nJOBS: 2\nMACHINES: 2\nJOB_SECTION\n'
        a.write_text(head.format(name='MOCK_A')+'1 2 1 2 2 3\n1 1 1 4\n')
        b.write_text(head.format(name='MOCK_B')+'1 1 1 4\n1 2 1 2 2 3\n')
        ra=p.structure(a,'train');rb=p.structure(b,'test')
        self.assertNotEqual(ra['ordered_operations_sha256'],rb['ordered_operations_sha256'])
        self.assertEqual(ra['job_relabel_invariant_sha256'],rb['job_relabel_invariant_sha256'])
        self.assertTrue(p.structure_audit([ra,rb])['blocks_execution'])
        self.assertEqual(ra['LB'],4.)

    def test_stats_mean_sign_exact_and_BCa_skew_acceleration(self):
        s=v.paired_statistics([0,0,0,3])
        self.assertAlmostEqual(s['delta_fitness'],.75)
        self.assertAlmostEqual(s['acceleration'],1/(6*math_sqrt(3)))
        self.assertEqual(s['BCa_status'],'ok')
        self.assertEqual(v.paired_statistics([1,1,1,1,1])['sign_test_p_two_sided'],.0625)

    def test_stats_scaling_swapping_and_seed_reproducible(self):
        data=np.array([-3.,-1.,0.,2.,7.]);a=v.paired_statistics(data);b=v.paired_statistics(-data);c=v.paired_statistics(2*data)
        np.testing.assert_allclose(a['BCa_95_CI'],[-b['BCa_95_CI'][1],-b['BCa_95_CI'][0]],rtol=1e-12,atol=1e-12)
        np.testing.assert_allclose(c['BCa_95_CI'],np.array(a['BCa_95_CI'])*2)
        self.assertEqual(a,v.paired_statistics(data));self.assertEqual(a['sign_test_p_two_sided'],b['sign_test_p_two_sided'])

    def test_stats_degeneracy_ties_nonfinite_and_no_fallback(self):
        s=v.paired_statistics([0,0,0]);self.assertIsNone(s['BCa_95_CI']);self.assertIsNone(s['sign_test_p_two_sided'])
        self.assertTrue(s['BCa_status'].startswith('undefined:'))
        for data in ([float('nan'),1],[float('inf'),1],[1]):
            with self.assertRaises(ValueError):v.paired_statistics(data)

    def test_BCa_unexpected_statistical_error_marked_without_method_change(self):
        with patch.object(np,'quantile',side_effect=RuntimeError('SYNTHETIC quantile failure')):
            r=v.paired_statistics([-1,0,1,2])
        self.assertIsNone(r['BCa_95_CI']);self.assertIn('RuntimeError',r['BCa_status'])
        self.assertEqual(r['delta_fitness'],.5);self.assertIsNotNone(r['sign_test_p_two_sided'])
        self.assertEqual(r['statistics_policy']['method'],p.STATISTICS['method'])

    def test_metadata_LB_retains_fractional_load_bound(self):
        path=self.root/'SYNTHETIC_FRACTIONAL.fjsp'
        path.write_text('NAME: MOCK\nTYPE: FJSP\nJOBS: 3\nMACHINES: 2\nJOB_SECTION\n'+'1 1 1 3\n'*3)
        self.assertEqual(p.structure(path,'test')['LB'],4.5)

    def test_task_result_cannot_be_adopted_under_wrong_identity(self):
        run=self.run_object();t=self.protocol['tasks'][0]
        run.state['tasks'][t['id']]={'status':'reserved'};run.save()
        atomic_json(self.root/'results'/(t['id']+'.json'),{'identity':'OTHER','mode':'mock','task':t,'result':success(t)})
        with self.assertRaises(ValueError):self.run_object().run(self.evaluate)
        self.assertFalse(self.calls)


def math_sqrt(x):return x**.5


if __name__=='__main__':unittest.main()
