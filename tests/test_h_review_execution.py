from dataclasses import asdict
import multiprocessing as mp
import time
import unittest

from fjsp_usage.research.candidates import H_ARGS, validate_code
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import review_member, load_h, seal
from fjsp_usage.research_real.review_execution import score_samples, ReviewExecutionError
from fjsp_usage.research_real.runtime import evaluate
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation


def h(body):
    return validate_code('def priority('+', '.join(H_ARGS)+'):\n'+body,kind='h')


class HReviewTests(unittest.TestCase):
    def test_train_valid_rule_can_loop_only_on_review_sample_and_is_killed(self):
        candidate = h('    if processing_time == 4 and remaining_work == 4 and job_ready_time == 5:\n'
                      '        while True:\n            pass\n    return -processing_time')
        instance = FJSPInstance('one',1,((Operation(((0,1),)),),))
        self.assertTrue(evaluate(candidate,(),(instance,),('one',),timeout=2)['valid'])
        before = {p.pid for p in mp.active_children()}
        started = time.monotonic()
        with self.assertRaisesRegex(ReviewExecutionError,'timed out'):
            score_samples(candidate,timeout=.35)
        self.assertLess(time.monotonic()-started,2)
        self.assertEqual({p.pid for p in mp.active_children()},before)

    def test_finite_samples_and_explicit_nonempty_review_required(self):
        candidate = h('    return -earliest_finish')
        self.assertEqual([r['score'] for r in score_samples(candidate)],[-5.,-9.,-1.])
        review = review_member(candidate,description='Smallest earliest finish scores highest.',
            reviewer='test supplied human metadata',method='explicit-test-review',note='synthetic test only')
        self.assertEqual(review['reviewed_code_key'],candidate.key)
        self.assertEqual(review['sample_sha256'],digest(review['samples']))
        with self.assertRaises(ValueError):
            review_member(candidate,description='',reviewer='person',method='manual',note='read')

    def test_boolean_exception_and_invalid_deadline_rejected(self):
        for expression in ('True','1/0'):
            with self.assertRaises(ReviewExecutionError):
                score_samples(h('    return '+expression))
        for timeout in (True,0,float('inf'),float('nan')):
            with self.assertRaises(ValueError):
                score_samples(h('    return -processing_time'),timeout=timeout)

    def test_frozen_h_loading_also_bounds_sample_execution(self):
        candidate = h('    while True:\n        pass\n    return 0')
        text = '{Test-only infinite loop.}\n```python\n'+candidate.code.rstrip()+'\n```'
        receipt = {'mode':'synthetic','model':'fixture','global_key':'test/0','ledger_identity':'fixture',
            'status':'completed','send_confirmed':True,'response_text':text,'response_sha256':digest(text)}
        result = {'valid':True,'total_instances':1,'fitness':-1.,'instances':[
            {'file':'one','makespan':1,'lower_bound':1.,'score':-1.}]}
        row = {'candidate':asdict(candidate),'receipt':receipt,'training_result':result,
            'fitness':-1.,'scores':[-1.],'member_id':0,'review':{
                'reviewed_code_key':candidate.key,'description':'Test','reviewer':'Test',
                'method':'manual-test','note':'Test'}}
        asset = seal({'kind':'H_frozen','mode':'synthetic','context':'test','member_count':2,
            'training_files':['one'],'members':[row,{**row,'member_id':1}]})
        started = time.monotonic()
        with self.assertRaisesRegex(ReviewExecutionError,'timed out'):
            load_h(asset,mode='synthetic',context='test',size=2,names=('one',),review_timeout=.3)
        self.assertLess(time.monotonic()-started,2)


if __name__ == '__main__': unittest.main()
