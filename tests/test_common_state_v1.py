"""Independent arithmetic checks for v1 sensors and missing/history boundaries."""
import copy
import math
import unittest
from dataclasses import replace

from heuristic_design.core.constructive_state import History, observe, plain, NUMERIC_FIELDS
from heuristic_design.problems.fjsp.common_state import precheck, actions_and_inputs, extract
from heuristic_design.problems.tsp import common_state as tsp
from heuristic_design.problems.tsp.solver import distances
from fjsp_usage.offline_v2 import _SchedulingState
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation


def asymmetric():
    return FJSPInstance('synthetic-asymmetric', 3, (
        (Operation(((0, 3),)), Operation(((0, 4), (1, 6), (2, 8)))),
        (Operation(((1, 2), (2, 5))),)))


class Tests(unittest.TestCase):
    def test_fjsp_manual_values_readonly_and_rescaling(self):
        instance = asymmetric()
        precheck(instance)
        s = _SchedulingState(instance)
        before = copy.deepcopy(s.__dict__)
        history = History(3, 2)
        actions, inputs = actions_and_inputs(s)
        p = extract(s, history, actions)
        self.assertEqual(s.__dict__, before)
        self.assertEqual(len(NUMERIC_FIELDS), 13)
        self.assertEqual(p['action_breadth_fraction'], 3/5)
        self.assertEqual(p['committed_objective_fraction'], 0)
        self.assertEqual(p['action_delta_min'], 2/16)
        self.assertEqual(p['action_delta_mean'], 10/48)
        self.assertAlmostEqual(p['action_delta_std'], math.sqrt(14/9)/16)
        self.assertEqual(p['action_delta_max'], 5/16)
        self.assertEqual(p['action_delta_best_gap'], 1/16)
        self.assertFalse(p['availability']['last_action_delta'])
        self.assertIsNone(p['previous_h_token'])
        self.assertIsNone(p['usage_fraction'])
        with self.assertRaises(TypeError): p['construction_progress'] = 1
        with self.assertRaises(TypeError): p['availability']['last_action_delta'] = True
        scaled = replace(instance, jobs=tuple(tuple(Operation(tuple((m, d*11) for m,d in op.alternatives)) for op in job) for job in instance.jobs))
        ss = _SchedulingState(scaled)
        self.assertEqual(plain(p), plain(extract(ss, History(3,2), actions_and_inputs(ss)[0])))

    def test_triangle_costs_and_forced_closure(self):
        d = distances([[0,0],[1,0],[0,1]])
        scale = tsp.precheck(d)
        h = History(2, 2)
        p = tsp.extract(d, [0], [1,2], 0., h, scale)
        self.assertEqual(p['action_delta_best_gap'], 0)
        self.assertEqual(p['action_delta_mean'], 1/(3*math.sqrt(2)))
        h.commit(1, 1/scale)
        p = tsp.extract(d, [0,1], [2], 1., h, scale)
        self.assertEqual(p['construction_progress'], .5)
        self.assertEqual(p['committed_objective_fraction'], 1/scale)
        self.assertEqual(p['action_delta_min'], 1/3)
        self.assertIsNone(p['action_delta_best_gap'])
        self.assertEqual(p['usage_fraction'], (0.,1.))
        self.assertEqual(p['current_h_run_fraction'], .5)
        self.assertFalse(p['availability']['recent_h_switch_fraction'])
        h.commit(0, 1/3)
        with self.assertRaises(ValueError): tsp.extract(d, [0,1,2], [], 1+math.sqrt(2), h, scale)
        with self.assertRaises(ValueError): tsp.precheck(distances([[0,0]]*3))

    def test_window_counts_masks_singleton_and_zero_deltas(self):
        h = History(8, 3, window=3)
        for member, delta in [(1,.1),(1,.2),(0,0.),(0,.4)]: h.commit(member, delta)
        p = observe('fjsp', history=h, action_bound=2, partial_cost=1, scale=10, action_deltas=[0,0])
        self.assertEqual(p['history_count'], 4)
        self.assertEqual(p['recent_history_count'], 3)
        self.assertEqual(p['current_h_run_fraction'], 2/8)
        self.assertEqual(p['recent_h_switch_fraction'], .5)
        self.assertEqual(p['usage_fraction'], (.5,.5,0))
        self.assertAlmostEqual(p['recent_delta_mean'], .2)
        self.assertEqual(p['action_delta_best_gap'], 0)
        disabled = observe('fjsp', history=h, action_bound=2, partial_cost=1, scale=10, action_deltas=[0], enabled_groups=('construction',))
        self.assertIsNone(disabled['action_delta_min'])
        self.assertEqual(disabled['missing_reason']['action_delta_min'], 'feature_group_disabled')
        self.assertIsNone(disabled['usage_fraction'])
        for scale, deltas in [(0,[0]),(1,[]),(1,[float('inf')]),(1,[-1])]:
            with self.assertRaises(ValueError): observe('fjsp',history=h,action_bound=2,partial_cost=0,scale=scale,action_deltas=deltas)
        with self.assertRaises(ValueError): History(1,1,0)
        with self.assertRaises(ValueError): h.commit(True,.1)


if __name__ == '__main__': unittest.main()
