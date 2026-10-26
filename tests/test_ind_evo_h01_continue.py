from copy import deepcopy
import unittest
from tools import ind_evo_h01_continue as c


class ContinuationTests(unittest.TestCase):
    def test_same_suffix_no_resampling_or_refill(self):
        tasks=c.x.plan();self.assertEqual(len(tasks[109:]),11)
        self.assertEqual([t['position'] for t in tasks[109:]],list(range(110,121)))
        self.assertEqual(len({t['task_id'] for t in tasks}),120)

    def test_old_request_content_is_immutable_while_new_appends(self):
        old={'requests':{'old':{'text':'first complete'}},'api_attempts':{'a':{'status':'completed'}}}
        new=deepcopy(old);new['requests']['new']={'text':'next'};new['api_attempts']['b']={'status':'completed'}
        self.assertEqual(c.prefix_digest(old,old),c.prefix_digest(new,old))
        new['requests']['old']['text']='changed'
        self.assertNotEqual(c.prefix_digest(old,old),c.prefix_digest(new,old))

    def test_budgets_still_inherited(self):
        self.assertEqual(c.x.POLICY['logical_candidate_cap'],20)
        self.assertEqual(c.x.POLICY['api_attempt_cap'],30)
        self.assertEqual(c.x.POLICY['per_candidate_attempt_cap'],2)
        self.assertLessEqual(109+11*2,180)


if __name__=='__main__':unittest.main()
