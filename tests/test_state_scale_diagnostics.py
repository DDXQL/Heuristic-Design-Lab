"""State proofs, conservative analysis and noninterfering coverage; toy data only."""
from dataclasses import asdict
import math
import random
import tempfile
import unittest
from unittest.mock import patch
import time

from fjsp_usage.research.candidates import U_ARGS,H_ARGS,validate_code,compile_candidate
from fjsp_usage.research.scheduler import construct_usage_schedule
from fjsp_usage.research_real.state_diagnostics import static_diagnostics,Coverage,state_contract
from fjsp_usage.research_real.prompts import build_prompt,prompt_manifest
from fjsp_usage.research_real.preparation import preview_members
from fjsp_usage.research_real.runtime import evaluate
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance,Operation


def u(body): return validate_code('def select_heuristic('+', '.join(U_ARGS)+'):\n    '+body.replace('\n','\n    ')+'\n')

def h(): return validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -earliest_finish\n',kind='h')


def slow_diagnostic(pipe, *args):
    time.sleep(1)
    pipe.close()


class StateScaleTests(unittest.TestCase):
    def test_many_legal_states_prove_normalization_including_unused_machines(self):
        rng=random.Random(43)
        for index in range(35):
            M=rng.randint(1,5); J=rng.randint(1,7)
            jobs=[]
            for j in range(J):
                ops=[]
                for k in range(rng.randint(1,5)):
                    machines=rng.sample(range(M),rng.randint(1,M))
                    ops.append(Operation(tuple(sorted((m,rng.randint(1,21)) for m in machines))))
                jobs.append(tuple(ops))
            instance=FJSPInstance(str(index),M,tuple(jobs)); traces=[]
            result=construct_usage_schedule(instance,(compile_candidate(h()),)*2,
                lambda *state:0,trace=traces.append,max_actions=0)
            self.assertEqual(len(traces),instance.operation_count)
            for r in traces:
                s=r['state']; self.assertLess(s['progress'],1)
                self.assertGreater(s['candidate_pair_ratio'],0); self.assertLessEqual(s['candidate_pair_ratio'],1)
                for mean,std in [('remaining_work_mean','remaining_work_std'),('machine_ready_mean','machine_ready_std')]:
                    m,d=s[mean],s[std]
                    self.assertTrue(0<=m<=1); self.assertTrue(0<=d<=.5)
                    self.assertLessEqual(d*d,m*(1-m)+1e-12)
                    self.assertLessEqual(d/(m+1),math.sqrt(2)/4+1e-12)
                self.assertEqual(s['previous_heuristic'],-1 if r['step']==0 else 0)
            self.assertEqual(result.selected_members,(0,)*instance.operation_count)

    def test_alias_arithmetic_machine_and_work_dead_branches_are_proven(self):
        candidate=u('w = remaining_work_mean\nd = remaining_work_std\nwd = d/(w+1)\nmd = machine_ready_std/(machine_ready_mean+1)\nif wd > 0.6 or md > 0.8:\n    return 1\nreturn 0')
        report=static_diagnostics(candidate.code,10)
        self.assertTrue(all(r['proof']=='always_false' for r in report['predicates'].values()))

    def test_joint_dispersion_bound_survives_finite_guards_casts_and_safe_clips(self):
        c=u('w = float(remaining_work_mean)\nd = float(remaining_work_std)\nm = float(machine_ready_mean)\ns = float(machine_ready_std)\nif w != w:\n    w = 0\nw = min(max(w, 0.0), 1e9)\nd = min(max(d, 0.0), 1e9)\nx = d/(w+1)\ny = s/(m+1)\nx = min(max(x,0.0),1.0)\nz = x+y\nif x > 0.4 or y > 0.4 or z > 1.0:\n    return 1\nreturn 0')
        report=static_diagnostics(c.code,10)
        self.assertTrue(all(r['proof']=='always_false' for r in report['predicates'].values()))
        # Changing a value (rather than aliasing/clipping to its legal range)
        # breaks the relation; diagnostics must not use the original bound.
        c=u('w = remaining_work_mean\nd = remaining_work_std\nw = 0\nreturn 1 if d/(w+1) > 0.4 else 0')
        self.assertTrue(all(r['proof']=='not_proven' for r in static_diagnostics(c.code,10)['predicates'].values()))

    def test_similar_intervals_are_not_value_identity_for_joint_bounds(self):
        # Both arguments have [0,1] bounds, but min() can reduce the actual
        # work mean. The original dispersion bound cannot then be applied.
        c=u('w = min(remaining_work_mean, candidate_pair_ratio)\nreturn 1 if remaining_work_std/(w+1) > 0.4 else 0')
        self.assertTrue(all(r['proof']=='not_proven' for r in static_diagnostics(c.code,10)['predicates'].values()))
        args=(0.,0.01,.5,.5,0.,0.,-1)
        self.assertEqual(compile_candidate(c)(*args),1)

    def test_unreachable_overflow_stays_unknown_without_crashing_diagnostics(self):
        c=u('if progress > 2:\n    x = (1e9**8)**8\n    if x > 1:\n        return 1\nreturn 0')
        r=static_diagnostics(c.code,2)
        row=next(v for v in r['predicates'].values() if v['expression']=='x > 1')
        self.assertEqual(row['proof'],'not_proven')
        self.assertEqual(compile_candidate(c)(0.,1.,.1,0.,0.,0.,-1),0)

    def test_unsupported_round_modulo_and_loop_assignments_stay_unknown(self):
        for body in ('x = round(machine_ready_std, 0)\nif x > 0.6:\n    return 1\nreturn 0',
                     'x = 0\nfor i in range(3):\n    x = 2\nif x > 0.6:\n    return 1\nreturn 0',
                     'x = progress % 0.2\nreturn 1 if x > 0.1 else 0'):
            r=static_diagnostics(u(body).code,2)
            self.assertTrue(all(p['proof']=='not_proven' for p in r['predicates'].values()))

    def test_branch_union_does_not_apply_first_branch_bounds_to_second(self):
        c=u('if progress > 0.5:\n    x = 0.1\nelse:\n    x = 0.9\nif x > 0.6:\n    return 1\nreturn 0')
        report=static_diagnostics(c.code,2)
        self.assertTrue(all(r['proof']=='not_proven' for r in report['predicates'].values()))

    def test_short_circuit_and_chained_compare_never_evaluate_extra_terms(self):
        c=u('if progress > 2 and 1/0 > 0:\n    return 1\nreturn 1 if 0 < progress < 0.5 else 0')
        obs=Coverage(c,2); f=compile_candidate(c,observer=obs.observe); plain=compile_candidate(c)
        for p in (0.,.2,.9):
            args=(p,1.,.1,0.,0.,0.,-1)
            self.assertEqual(f(*args),plain(*args))
        rows=obs.report()['predicates']
        zero=next(r for r in rows.values() if r['expression']=='1 / 0 > 0')
        self.assertEqual(zero['evaluations'],0)
        self.assertEqual(zero['proof'],'not_proven')

    def test_never_observed_is_distinct_from_never_possible(self):
        c=u('return 1 if machine_ready_std > 0.1 else 0')
        obs=Coverage(c,2); f=compile_candidate(c,observer=obs.observe)
        f(0.,1.,.2,0.,0.,0.,-1)
        for row in obs.report()['predicates'].values():
            self.assertEqual(row['proof'],'not_proven')
            self.assertEqual(row['observation'],'never_true_on_this_split')

    def test_runtime_replay_has_full_state_trajectory_and_separate_time(self):
        instance=FJSPInstance('toy',2,((Operation(((0,3),(1,2))),Operation(((0,1),))),
                                      (Operation(((1,4),)),)))
        c=u('return 0 if previous_heuristic == -1 else 1')
        result=evaluate(c,(h(),h()),(instance,),('toy',),timeout=3,diagnostics=True)
        self.assertTrue(result['valid'],result)
        row=result['instances'][0]
        self.assertEqual(len(row['state_trajectory']),3)
        self.assertEqual([r['member_id'] for r in row['state_trajectory']],[0,1,1])
        self.assertEqual(len(row['training_behavior_sha256']),64)
        for field in ('single_solve_seconds','deterministic_recheck_seconds','diagnostic_replay_seconds'):
            self.assertGreater(row[field],0)
        self.assertTrue(row['feasible'])

    def test_constant_U_and_partial_H_remain_legal_without_predicates(self):
        instance=FJSPInstance('toy',1,((Operation(((0,2),)),),))
        result=evaluate(u('return 0'),(h(),h()),(instance,),('toy',),diagnostics=True)
        self.assertTrue(result['valid'])
        self.assertEqual(result['instances'][0]['member_usage']['counts'],[1,0])
        self.assertEqual(result['selector_diagnostics']['predicates'],{})

    def test_runtime_failure_retains_null_makespan_and_unknown_solve_time(self):
        instance=FJSPInstance('toy',1,((Operation(((0,2),)),),))
        result=evaluate(u('return 9'),(h(),h()),(instance,),('toy',),diagnostics=True)
        self.assertFalse(result['valid']);self.assertIsNone(result['fitness'])
        row=result['failed_instance_result']
        self.assertIsNone(row['feasible']);self.assertFalse(row['valid']);self.assertIsNone(row['makespan'])
        self.assertIsNone(row['single_solve_seconds'])
        self.assertGreater(row['parent_observed_instance_seconds'],0)

    def test_diagnostic_timeout_cannot_invalidate_a_completed_primary_evaluation(self):
        instance=FJSPInstance('toy',1,((Operation(((0,2),)),),))
        candidate=u('return 0')
        plain=evaluate(candidate,(h(),h()),(instance,),('toy',),timeout=2)
        with patch('fjsp_usage.research_real.runtime._diagnostic_worker',slow_diagnostic):
            observed=evaluate(candidate,(h(),h()),(instance,),('toy',),timeout=2,
                diagnostics=True,diagnostic_timeout=.15)
        self.assertTrue(observed['valid']);self.assertEqual(observed['fitness'],plain['fitness'])
        self.assertFalse(observed['diagnostic_complete'])
        self.assertEqual(observed['diagnostic_failure']['error_type'],'Timeout')
        self.assertEqual(observed['instances'][0]['makespan'],2)
        self.assertEqual(observed['instances'][0]['diagnostic_status'],'not_completed')

    def test_prompt_has_exact_bounds_and_B2_P_common_context_same(self):
        from fjsp_usage.research_real.prompts import prompt_sections
        parents=[{'candidate':asdict(u('return 0'))},{'candidate':asdict(u('return 1'))}]
        a=prompt_sections('B2','CROSS',parents,preview_members())
        b=prompt_sections('P','CROSS',parents,preview_members())
        self.assertEqual({k:v for k,v in a.items() if k!='operator'},{k:v for k,v in b.items() if k!='operator'})
        self.assertIn('std <= 0.5',a['task_and_H'])
        self.assertIn('approximately 0.353554',a['task_and_H'])
        self.assertNotIn('H MEMBER',build_prompt('B0','I1',[],preview_members()))
        self.assertIn('v5-state-bounds',prompt_manifest()['version'])

if __name__=='__main__': unittest.main()
