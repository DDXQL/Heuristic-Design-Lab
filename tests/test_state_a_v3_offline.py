"""Per-H sensor/ABI checks on hand-given histories; never run H or a solver."""
import ast
from collections import Counter
from dataclasses import asdict
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from heuristic_design.core import state_a as old_state, routing_state_a as old_u
from heuristic_design.core import state_a_v3 as s, routing_state_a_v3 as u
from heuristic_design.core.state_contracts import make_binding, assert_same_binding
from heuristic_design.core.constructive_state import plain
from heuristic_design.core.storage import digest

ROOT = Path(__file__).resolve().parents[1]


def snapshot(history=None, problem='fjsp'):
    h = s.History(30, 3) if history is None else history
    return s.observe(problem, history=h, demands=[0.3], commitments=[0.1, 0.5], action_deltas=[0.2, 0.8])


class OfflineV3Tests(unittest.TestCase):
    def test_initial_counts_available_absent_means_and_gaps_unavailable(self):
        p = snapshot()
        for field in ('h_usage_count', 'h_recent_usage_count'):
            self.assertEqual(p[field], (0, 0, 0))
            self.assertEqual(p['availability'][field], (True, True, True))
        for field in ('h_last_use_gap_fraction', 'h_recent_delta_mean'):
            self.assertEqual(p[field], (None, None, None))
            self.assertEqual(p['availability'][field], (False, False, False))
        self.assertEqual(p['missing_reason']['h_last_use_gap_fraction'], ('never_used',) * 3)
        with self.assertRaises(TypeError):
            p['h_usage_count'][0] = 1
        with self.assertRaises(TypeError):
            p['availability']['h_recent_delta_mean'][0] = True

    def test_global_window_eviction_zero_observation_and_history_reset(self):
        h = s.History(30, 3)
        h.commit(0, 0.9)
        for _ in range(11):
            h.commit(1, 0.2)
        p = snapshot(h)
        self.assertEqual(p['h_usage_count'], (1, 11, 0))
        self.assertEqual(p['h_recent_usage_count'], (0, 10, 0))
        self.assertAlmostEqual(p['h_last_use_gap_fraction'][0], 11/30)
        self.assertEqual(p['h_last_use_gap_fraction'][1:], (0, None))
        self.assertIsNone(p['h_recent_delta_mean'][0])  # previously used, no recent sample
        self.assertAlmostEqual(p['h_recent_delta_mean'][1], 0.2)
        h.commit(2, 0)
        p = snapshot(h)
        self.assertEqual(p['h_recent_usage_count'], (0, 9, 1))
        self.assertEqual(p['h_recent_delta_mean'][2], 0)
        self.assertTrue(p['availability']['h_recent_delta_mean'][2])
        self.assertEqual(p['h_last_use_gap_fraction'][2], 0)
        self.assertEqual(snapshot()['h_usage_count'], (0, 0, 0))

    def test_rejected_commits_leave_all_history_unchanged(self):
        h = s.History(3, 3)
        h.commit(0, 0.5)
        before = (h.count, tuple(h.counts), tuple(h.last_use), tuple(h.recent))
        for member, delta in [(True, 0), (-1, 0), (3, 0), (0, float('nan')), (0, 1.1)]:
            with self.assertRaises(ValueError):
                h.commit(member, delta)
            self.assertEqual(before, (h.count, tuple(h.counts), tuple(h.last_use), tuple(h.recent)))
        with self.assertRaises(ValueError):
            s.History(30, 3, window=11)

    def test_three_problem_adapters_reuse_the_ten_scalar_definitions(self):
        from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation
        from heuristic_design.problems.fjsp import state_a as f2, state_a_v3 as f3
        from heuristic_design.problems.fjsp.common_state import actions_and_inputs
        from heuristic_design.problems.tsp import state_a as t2, state_a_v3 as t3
        from heuristic_design.problems.obp import state_a as o2, state_a_v3 as o3
        instance = FJSPInstance('manual-state', 2, (
            (Operation(((0, 2), (1, 4))), Operation(((1, 3),))),
            (Operation(((0, 6), (1, 2))),),
        ))
        state = SimpleNamespace(instance=instance, cursors=[1, 0], job_ready=[4, 0], machine_ready=[0, 4],
                                remaining_work=[(5, 3, 0), (2, 0)], scheduled=[object()])
        h = s.History(3, 3)
        h.commit(1, 2/3)
        actions, _ = actions_and_inputs(state)
        old, new = f2.Sensors(instance).extract(state, h, actions), f3.Sensors(instance).extract(state, h, actions)
        for field in old_state.FIELDS:
            self.assertEqual(old[field], new[field])
        self.assertEqual(new['h_usage_count'], (0, 1, 0))
        self.assertEqual(new['h_recent_delta_mean'], (None, 2/3, None))
        d = np.array([[0, 1, 2, 3], [1, 0, 4, 5], [2, 4, 0, 6], [3, 5, 6, 0]], dtype=float)
        tsp_history, obp_history = s.History(3, 3), s.History(5, 3)
        tsp_history.commit(1, 1/3)  # given edge 0->2 has length 2, dmax=6
        obp_history.commit(1, 1)    # given first item opened the first bin
        for old, new in (
            (t2.Sensors(d).extract([0, 2], [1, 3], tsp_history), t3.Sensors(d).extract([0, 2], [1, 3], tsp_history)),
            (o2.extract(3, [4], 10, obp_history)[0], o3.extract(3, [4], 10, obp_history)[0]),
        ):
            for field in old_state.FIELDS:
                self.assertEqual(old[field], new[field])
            self.assertEqual(new['h_recent_usage_count'], (0, 1, 0))
        fresh, _ = o3.extract(4, [], 10, s.History(5, 3))
        self.assertIsNone(fresh['resource_commitment_mean'])
        self.assertEqual(fresh['remaining_demand_std'], 0)
        self.assertEqual(tuple(inspect.signature(o3.extract).parameters), ('current_item', 'opened_used', 'capacity', 'history'))

    def test_packet_shapes_counts_masks_versions_and_absence_rules(self):
        h = s.History(30, 3)
        h.commit(0, 0.25)
        p = plain(snapshot(h))
        changes = [dict(h_usage_count=[True, 0, 0]), dict(h_usage_count=[2, 0, 0]),
                   dict(h_recent_usage_count=[0, 1, 0]), dict(h_usage_count=[1, 0]),
                   dict(h_recent_delta_mean=[0.25, 0, None]), dict(h_last_use_gap_fraction=[1, None, None]),
                   dict(spec_sha256='old'), dict(schema_id=old_state.schema_id('fjsp')),
                   dict(offline_h_fitness=[0, 0, 0])]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                s.validate_packet({**p, **change}, 3)
        bad = plain(snapshot(h))
        bad['availability']['h_recent_delta_mean'][0] = False
        with self.assertRaises(ValueError):
            s.validate_packet(bad, 3)
        bad = plain(snapshot(h))
        bad['h_recent_delta_mean'][0] = 0.7
        with self.assertRaises(ValueError):
            s.validate_packet(bad, 3)
        with self.assertRaises(ValueError):
            old_state.validate_packet(snapshot(h), 3)

    def test_literal_array_reads_per_item_masks_and_observed_read_paths(self):
        code = '''def use_heuristics(state):
    if state["availability"]["h_recent_delta_mean"][0]:
        if state["h_recent_delta_mean"][0] < 0.5:
            return 0
    if state["h_usage_count"][2] == 0:
        return 2
    return 1
'''
        c = u.validate(code, member_count=3)
        reads = Counter()
        fn = u.compile_candidate(c, 3, reads=reads)
        self.assertEqual(fn(snapshot()), 2)
        self.assertEqual(reads['availability.h_recent_delta_mean[0]'], 1)
        self.assertNotIn('h_recent_delta_mean[0]', reads)
        self.assertEqual(reads['h_usage_count[2]'], 1)
        h = s.History(30, 3)
        h.commit(0, 0)
        self.assertEqual(fn(snapshot(h)), 0)
        self.assertEqual(reads['h_recent_delta_mean[0]'], 1)
        self.assertEqual(u.inspect_reads(code, 3)['read_paths'],
                         ['availability.h_recent_delta_mean[0]', 'h_recent_delta_mean[0]', 'h_usage_count[2]'])
        for field in s.H_FIELDS:
            u.validate(f'def use_heuristics(state):\n if state["availability"]["{field}"][0]:\n  x = state["{field}"][0]\n return 0', member_count=3)
        parsed = u.parse('A router\n```python\n' + c.code.rstrip() + '\n```', 3)
        self.assertEqual(c.key, parsed.key)

    def test_forbidden_indices_aliases_containers_and_foreign_candidates(self):
        for expr in ('state["h_usage_count"]', 'state["h_usage_count"][-1]', 'state["h_usage_count"][3]',
                     'state["h_usage_count"][True]', 'state["h_usage_count"][0.0]', 'state["h_usage_count"][int(0)]',
                     'state["availability"]["h_recent_delta_mean"]', 'state["availability"]["h_recent_delta_mean"][3]',
                     'state["availability"]["construction_progress"][0]', 'state["schema_id"]',
                     'state["usage_fraction"][0]', 'state.__class__', '__import__("os")', '[0][0]'):
            with self.subTest(expr=expr), self.assertRaises(u.CandidateError):
                u.validate('def use_heuristics(state):\n return ' + expr, member_count=3)
        for body in ('x = state["h_usage_count"]\n return x[0]',
                     'i = 0\n return state["h_usage_count"][i]',
                     'state["h_usage_count"][0] = 1\n return 0', 'while True:\n  pass\n return 0'):
            with self.assertRaises(u.CandidateError):
                u.validate('def use_heuristics(state):\n ' + body.replace('\n', '\n '), member_count=3)
        old = old_u.validate('def use_heuristics(state):\n return 0', member_count=3)
        new = u.validate(old.code, member_count=3)
        self.assertNotEqual(old.key, new.key)
        with self.assertRaises(u.CandidateError):
            u.checked(asdict(old), 3)
        with self.assertRaises(old_u.CandidateError):
            old_u.checked(asdict(new), 3)
        with self.assertRaises(old_u.CandidateError):
            old_u.validate('def use_heuristics(state):\n return state["h_usage_count"][0]', member_count=3)
        for value in ('True', '0.0', '3', '-1', 'None'):
            fn = u.compile_candidate(u.validate('def use_heuristics(state):\n return ' + value, member_count=3), 3)
            with self.assertRaises(ValueError):
                fn(snapshot())

    def test_prompt_schema_binding_and_frozen_spec(self):
        c = u.validate('def use_heuristics(state):\n return 0', member_count=3)
        for problem in s.PROBLEMS:
            text = u.build_prompt(problem, {'operator': 'CROSS'},
                [{'id': 'original-v3', 'candidate': asdict(c)}], [{'id': 'H0'}, {'id': 'H1'}, {'id': 'H2'}])
            for expected in (u.ABI, s.SPEC_SHA256, *s.H_FIELDS, 'K=3', 'GLOBAL', 'MINIMIZE', 'original-v3', c.key):
                self.assertIn(expected, text)
            self.assertNotIn(old_u.ABI, text)
            self.assertNotIn(old_state.SPEC_SHA256, text)
        args = dict(problem_id='fjsp', state_schema=s.schema_id('fjsp'), policy_sha256=c.key,
                    h_order=['H0', 'H1', 'H2'], data_order=['future-train'], reference_sha256='lb-v5',
                    solve_seed=501, u_interface=u.ABI, action_schema='append-v1', objective='relative-gap-min',
                    normalization=s.SPEC_SHA256, tie_rule='first-max', evaluator_sha256='future-evaluator')
        b = make_binding(**args)
        self.assertTrue(assert_same_binding(b, b))
        for delta in (dict(u_interface=old_u.ABI), dict(normalization=old_state.SPEC_SHA256), dict(objective='maximize')):
            with self.assertRaises(ValueError):
                make_binding(**{**args, **delta})
        frozen = json.loads((ROOT / 'docs/state-a-v3/contract.json').read_text())
        self.assertEqual(frozen['spec_sha256'], s.SPEC_SHA256)
        self.assertEqual(digest(frozen['spec']), s.SPEC_SHA256)

    def test_selected_h_only_and_post_commit_history_in_host_source(self):
        for path, function in [('code/heuristic_design/problems/fjsp/routing.py', 'construct'),
                               ('code/heuristic_design/problems/tsp/routing.py', 'construct'),
                               ('code/heuristic_design/problems/obp/state_a_v3.py', 'step')]:
            tree = ast.parse((ROOT / path).read_text())
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function)
            calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
            experts = [n for n in calls if isinstance(n.func, ast.Subscript) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'members']
            self.assertEqual(len(experts), 1)
            self.assertEqual(ast.unparse(experts[0].func), 'members[member]')
            route = next(n for n in calls if isinstance(n.func, ast.Name) and n.func.id == 'usage')
            commit = next(n for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == 'commit')
            self.assertLess(route.lineno, experts[0].lineno)
            self.assertLess(experts[0].lineno, commit.lineno)
        from heuristic_design.problems.fjsp.routing import construct_state_a, construct_state_a_v3
        self.assertEqual(inspect.signature(construct_state_a), inspect.signature(construct_state_a_v3))


if __name__ == '__main__':
    unittest.main()
