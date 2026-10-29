"""Closed routing language, real solve parity, call order and identity isolation."""
from dataclasses import asdict
import unittest
import numpy as np
from heuristic_design.core import routing as c
from heuristic_design.core.constructive_state import schema_id
from heuristic_design.core.state_contracts import make_binding, assert_same_binding, legacy_packet
from heuristic_design.problems.fjsp.routing import construct as fjsp
from heuristic_design.problems.tsp.routing import construct as tsp
from heuristic_design.problems.tsp.solver import distances, construct as old_tsp
from fjsp_usage.offline_v2 import construct_usage_schedule as old_fjsp
from test_common_state_v1 import asymmetric


def h0(*a): return -a[-1]
def h1(*a): return -a[0]


class Tests(unittest.TestCase):
    def test_closed_access_and_runtime_tokens(self):
        good = '''def use_heuristics(state):
    if state["availability"]["usage_fraction"]:
        if state["usage_fraction"][1] > 0.5:
            return 0
    return 1
'''
        p = c.validate(good, member_count=2)
        u = c.compile_candidate(p, 2)
        self.assertEqual(u({'availability':{'usage_fraction':False},'usage_fraction':None}), 1)
        for body in ['return state.__class__', 'return state["schema_id"]',
                     'return state["usage_fraction"][2]', 'return state["usage_fraction"][-1]',
                     'return state["usage_fraction"][int(0)]', 'return state["availability"]["bogus"]',
                     'state["history_count"] = 4\n    return 0', 'x = state\n    return 0',
                     'return __import__("os")', 'while True:\n        pass\n    return 0',
                     'return (0, (1,0))', 'return [0][0]', 'return 10 ** 100000']:
            with self.subTest(body=body), self.assertRaises(c.CandidateError):
                c.validate('def use_heuristics(state):\n    '+body+'\n', member_count=2)
        for value in ['True', '-1', '2', '0.0', 'None']:
            p = c.validate('def use_heuristics(state):\n    return '+value, member_count=2)
            with self.assertRaises(ValueError): c.compile_candidate(p, 2)({})
        with self.assertRaises(c.CandidateError): c.checked({**asdict(p),'abi':'legacy'},2)

    def test_real_fjsp_legacy_parity_and_only_selected_h(self):
        instance = asymmetric()
        for member in (0,1):
            a = fjsp(instance, [h0,h1], lambda s:member)
            b = old_fjsp(instance,[h0,h1],lambda *s:member)
            self.assertEqual((a.schedule,a.score),(b.schedule,b.score))
            self.assertEqual(a.h_calls[1-member],0)
            self.assertEqual(len(a.trace),instance.operation_count)
        code = 'def use_heuristics(state):\n    return 1 if state["construction_progress"] > 0.5 else 0\n'
        r = fjsp(instance,[h0,h1],c.compile_candidate(c.validate(code,member_count=2),2))
        self.assertEqual([t['member_id'] for t in r.trace],[0,0,1])
        self.assertIsNone(r.trace[0]['state']['previous_h_token'])
        self.assertEqual(r.trace[1]['state']['previous_h_token'],0)
        self.assertEqual(r.trace[1]['state']['last_action_delta'],r.trace[0]['committed_delta'])
        def bad(*args): raise AssertionError('unselected H invoked')
        fjsp(instance,[h0,bad],lambda s:0)

    def test_real_tsp_parity_and_recheck(self):
        for n in (3,4,12):
            d = distances(np.random.default_rng(n).random((n,2)))
            for member in (0,1):
                a = tsp(d,[h0,h1],lambda s:member)
                b = old_tsp(d,[h0,h1],lambda *s:(0,tuple(int(i==member) for i in range(2))))
                self.assertEqual((a.tour,a.length),(b.tour,b.length))
                self.assertEqual(a.h_calls[1-member],0)
                self.assertEqual(len(a.trace),n-1)
                self.assertEqual(a.trace,tsp(d,[h0,h1],lambda s:member).trace)
                self.assertFalse(a.trace[-1]['state']['availability']['action_delta_best_gap'])

    def test_binding_rejects_cross_schema_problem_and_policy(self):
        args = dict(problem_id='fjsp',state_schema=schema_id('fjsp'),policy_sha256='U',h_order=['h0','h1'],
                    data_order=['toy'],reference_sha256='lb',solve_seed=501,u_interface=c.ABI,
                    action_schema='fjsp-action-v1',objective='-Cmax/LB',normalization='B',
                    tie_rule='first-max',evaluator_sha256='source')
        a = make_binding(**args)
        self.assertTrue(assert_same_binding(a,a))
        for change in [dict(state_schema='fjsp-seven-v1-legacy'),dict(policy_sha256='U2'),dict(solve_seed=502),dict(h_order=['h1','h0'])]:
            with self.assertRaises(ValueError): assert_same_binding(a, make_binding(**{**args,**change}))
        with self.assertRaises(ValueError): make_binding(**{**args,'state_schema':schema_id('tsp')})
        with self.assertRaises(ValueError): legacy_packet('fjsp', [0]*7,member_count=2,schema_id=schema_id('fjsp'))

    def test_prompt_matches_abi_and_contains_exact_parents(self):
        code = c.validate('def use_heuristics(state):\n return 0',member_count=2)
        prompt = c.build_prompt('fjsp',{'operator':'MUTATE'},[{'id':'original','candidate':asdict(code)}],[{'id':'H0'},{'id':'H1'}])
        for part in [c.ABI, 'previous_h_token', 'action_delta_std', 'original', 'No MIX', code.key]:
            self.assertIn(part,prompt)


if __name__ == '__main__': unittest.main()
