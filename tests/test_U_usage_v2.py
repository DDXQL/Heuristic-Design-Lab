"""Independent handwritten toys; never model-generated or real P0 assets."""
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
import math
from unittest.mock import patch
from fjsp_usage.research.candidates import U_ARGS,H_ARGS,CandidateError,validate_code,compile_candidate
from fjsp_usage.research.scheduler import construct_usage_schedule as legacy_schedule
from fjsp_usage.research_real.runtime import evaluate
from fjsp_usage.research_real.state_diagnostics import Coverage
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance,Operation
from llm4ad.task.optimization.fjsp_set.scheduler import validate_schedule
from fjsp_usage.usage_v2 import VERSION
from fjsp_usage.usage_v2.execution import (construct_usage_schedule,decode_output,combine_scores,LegacyAdapter,
    UsageOutputError,NormalizationError,usage_summary)
from fjsp_usage.usage_v2.exports import export_prompts


def candidate(body,size=3):return validate_code('def use_heuristics('+', '.join(U_ARGS)+'):\n    '+body.replace('\n','\n    ')+'\n',interface_version=VERSION,member_count=size)
def h(body):return validate_code('def priority('+', '.join(H_ARGS)+'):\n    '+body+'\n',kind='h')
def toy():return FJSPInstance('usage-toy',2,((Operation(((0,2),(1,3))),Operation(((0,5),(1,6)))),(Operation(((0,4),)),)))

class UsageTests(unittest.TestCase):
    def test_only_terminal_tuple_language_and_precise_signature(self):
        c=candidate('return (0, (progress, -2, previous_heuristic))')
        self.assertEqual(compile_candidate(c)(.2,.5,.1,0,0,0,-1),(0,(.2,-2,-1)))
        for body in ('v=(1,2,3)\nreturn (0,v)','return (0,[1,2,3])','return (0,(1, (2,3),0))',
                     'return (0,(min((1,2)),0,0))','return (0,(globals(),0,0))','return (0,(1,2))'):
            with self.subTest(body=body),self.assertRaises(CandidateError):candidate(body)
        with self.assertRaises(CandidateError):validate_code(c.code)
        with self.assertRaises(CandidateError):validate_code(c.code,interface_version='unknown')
        with self.assertRaises(CandidateError):validate_code(c.code,interface_version=VERSION,kind='h')

    def test_field_guards_reject_nonfinite_intermediate_before_output(self):
        fn=compile_candidate(candidate('x = 1e9 ** 8\nx = x * x\nreturn (0, (x,0,0))'))
        with self.assertRaises(ValueError):fn(0,1,.1,0,0,0,-1)
        fn=compile_candidate(candidate('return (1, (True,1,0))'))
        with self.assertRaises(UsageOutputError):decode_output(fn(0,1,.1,0,0,0,-1),3)

    def test_select_negative_zero_and_exact_ties(self):
        for v,k in (((-4,-2,-3),1),((0,0,0),0),((4,4,1),0),((2**54,2**54+1,0),1)):
            self.assertEqual(decode_output((0,v),3)['support'],(k,))
        self.assertEqual(decode_output((0,(1,1+1e-12,0)),3)['support'],(1,))

    def test_output_failures_and_mode_policy_before_h(self):
        bad=(0,[0,1,2],(0,(1,2)),(True,(1,0,0)),(0.0,(1,0,0)),(2,(1,0,0)),
             (1,(0,0,0)),(1,(-1,1,0)),(1,(1,1,1)),(0,(math.nan,0,0)),(0,(math.inf,0,0)),
             (0,(True,0,0)),(1,('1',0,0)),(0,(None,1,0)),(1,(1e100,1e-300,0)))
        for out in bad:
            count=[]
            def rule(*args):count.append(args);return 1
            with self.subTest(out=out),self.assertRaises((UsageOutputError,NormalizationError)):
                construct_usage_schedule(toy(),[rule]*3,lambda *args:out)
            self.assertEqual(count,[])
        with self.assertRaises(UsageOutputError):construct_usage_schedule(toy(),[lambda *a:1]*3,lambda *a:(1,(1,1,0)),allowed_modes=(0,))

    def test_weight_support_and_dominant_history(self):
        self.assertEqual(decode_output((1,(0,5,0)),3)['weights'],(0,1,0))
        self.assertEqual(decode_output((1,(1,1,0)),3)['dominant'],0)
        self.assertEqual(decode_output((1,(.9,0,.1)),3)['dominant'],0)
        states=[]
        def u(*args):states.append(args);return (1,(1,1,0))
        first=construct_usage_schedule(toy(),[lambda *a:1]*3,u)
        self.assertEqual([x[-1] for x in states],[-1,0,0])
        states.clear();construct_usage_schedule(toy(),[lambda *a:1]*3,u)
        self.assertEqual(states[0][-1],-1)

    def test_hand_calculation_and_scale_effect(self):
        d=decode_output((1,(3,2,0)),3)
        f,info=combine_scores({0:(10,6,0),1:(0,80,100)},d['weights'],d['support'])
        expected=(Fraction(3,5),Fraction(17,25),Fraction(2,5))
        for actual,e in zip(f,expected):self.assertAlmostEqual(actual,float(e),places=12)
        self.assertEqual(max(range(3),key=lambda i:f[i]),1)
        self.assertEqual(info['normalized'],{0:(1,.6,0),1:(0,.8,1)})
        self.assertEqual(max(range(3),key=lambda i:.6*(10,6,0)[i]+.4*(0,80,100)[i]),2)

    def test_constant_column_unique_action_and_numeric_stability(self):
        f,n=combine_scores({0:(5,5,5),1:(0,5,10)},(.5,.5),(0,1))
        self.assertEqual(f,(0,.25,.5))
        self.assertEqual(combine_scores({0:(1,),1:(5,)},(.5,.5),(0,1))[0],(0,))
        self.assertEqual(combine_scores({0:(-1e308,1e308),1:(0,1)},(.5,.5),(0,1))[0],(0,1))
        a=combine_scores({0:(-2,0,4),1:(0,2,1)},(.3,.7),(0,1))[0]
        b=combine_scores({0:(4,10,22),1:(-5,-1,-3)},(.3,.7),(0,1))[0]
        for x,y in zip(a,b):self.assertAlmostEqual(x,y)

    def test_three_checkable_first_actions(self):
        matrix={2:(10,0,2),3:(6,80,0),4:(0,100,20),5:(1,1,1),6:(1,1,1)}
        rules=[lambda *args,i=i:matrix[int(args[0])][i] for i in range(3)]
        choices=[]
        for out in ((0,(0,0,1)),(0,(3,2,1)),(1,(3,2,0))):
            trajectory=[];result=construct_usage_schedule(toy(),rules,lambda *a:out,trace=trajectory.append)
            validate_schedule(toy(),result.schedule)
            choices.append((result.schedule.operations[0].job,result.schedule.operations[0].machine))
            self.assertEqual(trajectory[0]['state']['previous_heuristic'],-1)
        self.assertEqual(choices,[(1,0),(0,0),(0,1)])

    def test_legacy_constant_and_state_selector_exact_semantic_equivalence(self):
        rules=[lambda p,w,n,j,m,s,f:-f,lambda p,w,n,j,m,s,f:w-p,lambda *args:0]
        selectors=[lambda *args:1,lambda p,c,w,d,m,s,q:0 if p<.5 else 2,
            lambda p,c,w,d,m,s,q:2 if q==-1 else (q+1)%3]
        for u in selectors:
            old=[];new=[]
            first=legacy_schedule(toy(),rules,u,trace=old.append)
            adapter=LegacyAdapter(u,3,'HANDWRITTEN_TEST_ONLY')
            second=construct_usage_schedule(toy(),rules,adapter,trace=new.append)
            self.assertEqual(first.schedule,second.schedule);self.assertEqual(first.selected_members,second.selected_members)
            self.assertEqual(first.score,second.score)
            self.assertEqual([r['state'] for r in old],[r['state'] for r in new])
            self.assertEqual([r['chosen'] for r in old],[r['chosen'] for r in new])
            for r in new:self.assertEqual(r['support'],(r['dominant'],))
            third=construct_usage_schedule(toy(),rules,lambda *a:(1,adapter(*a)[1]))
            self.assertEqual(second.schedule,third.schedule);self.assertEqual(second.selected_members,third.selected_members)
        for k in (-1,3,True,1.0):
            with self.assertRaises(UsageOutputError):LegacyAdapter(lambda *a:k,3,'TEST')(*([0]*7))

    def test_single_path_no_floating_normalization_tie_collapse(self):
        values=(1,math.nextafter(1,math.inf),0)
        self.assertEqual(combine_scores({1:values},(0,1,0),(1,))[0],values)

    def test_calls_once_per_step_and_once_per_selected_h_action(self):
        calls=[0,0,0];u_count=[];trace=[]
        def u(*a):u_count.append(a);return (1,(1,1,0))
        def rule(i):
            def f(*a):calls[i]+=1;return -a[-1]
            return f
        def unused(*a):raise AssertionError('unselected member called')
        result=construct_usage_schedule(toy(),[rule(0),rule(1),unused],u,trace=trace.append,max_actions=0)
        self.assertEqual(len(u_count),toy().operation_count)
        count=sum(t['action_count'] for t in trace)
        self.assertEqual(calls,[count,count,0]);self.assertEqual(result.member_calls,(count,count,0))
        self.assertTrue(all(t['actions_truncated'] and not t['actions'] for t in trace))

    def test_action_ties_and_failed_selected_member(self):
        result=construct_usage_schedule(toy(),[lambda *a:0]*3,lambda *a:(1,(1,1,0)))
        self.assertEqual((result.schedule.operations[0].job,result.schedule.operations[0].machine),(0,0))
        for bad in (math.nan,math.inf,True,'bad'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                construct_usage_schedule(toy(),[lambda *a:bad]*3,lambda *a:(0,(1,0,0)))

    def test_runtime_determinism_observation_full_failure_and_cost_separation(self):
        rules=[h('return -earliest_finish'),h('return remaining_work'),h('return 0')]
        c=candidate('return (1,(3,2,0))')
        result=evaluate(c,rules,[toy()],['toy'],timeout=10,diagnostics=True,allowed_modes=(0,1))
        self.assertTrue(result['valid']);self.assertTrue(result['diagnostic_complete'])
        row=result['instances'][0]
        self.assertEqual(row['member_usage']['MIX_steps'],3)
        self.assertEqual(len(row['usage_decisions']),3)
        self.assertGreaterEqual(row['combination_processing_seconds'],0)
        self.assertGreater(row['deterministic_recheck_seconds'],0)
        self.assertEqual(len(row['state_trajectory']),3)
        self.assertEqual(row['single_h_calls'],row['deterministic_recheck_h_calls'])
        self.assertEqual(row['single_h_calls'],row['diagnostic_h_calls'])
        self.assertGreaterEqual(row['diagnostic_combination_processing_seconds'],0)
        invalid=evaluate(c,rules,[toy(),toy()],['first','second'],timeout=10,allowed_modes=(0,))
        self.assertFalse(invalid['valid']);self.assertIsNone(invalid['fitness']);self.assertEqual(invalid['failed_instance'],'first')
        self.assertIsNone(invalid['failed_instance_result']['makespan'])

    def test_observer_no_change_and_predicate_bounds(self):
        c=candidate('if progress < 0.5:\n    return (0,(1,0,0))\nreturn (1,(1,1,0))')
        coverage=Coverage(c,3);normal=compile_candidate(c);observed=compile_candidate(c,observer=coverage.observe)
        rules=[lambda *a:-a[-1]]*3
        self.assertEqual(construct_usage_schedule(toy(),rules,normal),construct_usage_schedule(toy(),rules,observed))
        self.assertTrue(coverage.report()['predicates'])

    def test_exported_complete_prompts_only_mode_diff(self):
        members=[h('return -earliest_finish')]*3
        with tempfile.TemporaryDirectory() as tmp:
            record=export_prompts(tmp,members,262144)
            self.assertEqual([r['changed_sections'] for r in record['comparison']],[[],['allowed_modes'],['allowed_modes']])
            self.assertEqual((Path(tmp)/'A.I1.txt').read_text(),(Path(tmp)/'B.I1.txt').read_text())
            self.assertIn('HANDWRITTEN_PREVIEW',record['parents'][0]['id'])
            self.assertIn('use_heuristics',(Path(tmp)/'B.CROSS.txt').read_text())

if __name__=='__main__':unittest.main()
