"""Sensor arithmetic, history and U ABI only. Never call a constructor or H."""
import ast
from collections import Counter
from dataclasses import asdict
import json
import inspect
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from heuristic_design.core import state_a as s, routing_state_a as u, routing as old
from heuristic_design.core.state_contracts import make_binding, assert_same_binding
from heuristic_design.core.constructive_state import plain
from heuristic_design.core.storage import digest
from heuristic_design.problems.fjsp.state_a import Sensors as FJSPSensors
from heuristic_design.problems.fjsp.common_state import actions_and_inputs
from heuristic_design.problems.tsp.state_a import Sensors as TSPSensors
from heuristic_design.problems.obp.state_a import extract as obp, legal_actions
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation

ROOT = Path(__file__).resolve().parents[1]


def packet(problem='fjsp', count=0):
    h = s.History(30, 2)
    for i in range(count):
        h.commit(i % 2, (i % 3) / 2)
    return s.observe(problem, history=h, demands=[0.2, 0.6], commitments=[0.0, 0.8], action_deltas=[0.0, 1.0])


class OfflineTests(unittest.TestCase):
    def test_frozen_spec_and_common_readable_fields(self):
        frozen = json.loads((ROOT / 'docs/state-a-v2/contract.json').read_text())
        self.assertEqual(frozen['spec_sha256'], s.SPEC_SHA256)
        self.assertEqual(digest(frozen['spec']), s.SPEC_SHA256)
        self.assertEqual(len(s.NUMERIC_FIELDS), 10)
        for problem in s.PROBLEMS:
            self.assertEqual(set(packet(problem, 1)) - set(s.SPEC['host_only']), set(s.FIELDS) | {'availability'})

    def test_fjsp_hand_given_initial_and_partial_state(self):
        instance = FJSPInstance('manual-observation', 2, (
            (Operation(((0, 2), (1, 4))), Operation(((1, 3),))),
            (Operation(((0, 6), (1, 2))),),
        ))
        sensor = FJSPSensors(instance)
        self.assertEqual((sensor.time_bound, sensor.pmax, sensor.decisions), (13, 6, 3))
        # These are supplied snapshots, not the output of scheduling.
        state = SimpleNamespace(instance=instance, cursors=[0, 0], job_ready=[0, 0],
                                machine_ready=[0, 0], remaining_work=[(5, 3, 0), (2, 0)], scheduled=[])
        h = s.History(3, 2)
        actions, _ = actions_and_inputs(state)
        p = sensor.extract(state, h, actions)
        self.assertEqual(p['legal_action_count'], 4)
        self.assertAlmostEqual(p['remaining_demand_mean'], 7/26)
        self.assertAlmostEqual(p['remaining_demand_std'], 3/26)
        self.assertEqual((p['resource_commitment_mean'], p['resource_commitment_std']), (0, 0))
        self.assertAlmostEqual(p['action_delta_mean'], 7/12)
        self.assertAlmostEqual(p['action_delta_std'], math.sqrt(11)/12)
        self.assertIsNone(p['recent_delta_mean'])
        state.cursors, state.job_ready, state.machine_ready, state.scheduled = [1, 0], [4, 0], [0, 4], [object()]
        h.commit(1, 2/3)
        before = (tuple(state.cursors), tuple(state.machine_ready), tuple(h.recent))
        actions, _ = actions_and_inputs(state)
        p = sensor.extract(state, h, actions)
        self.assertAlmostEqual(p['construction_progress'], 1/3)
        self.assertAlmostEqual(p['remaining_demand_mean'], 5/26)
        self.assertAlmostEqual(p['remaining_demand_std'], 1/26)
        self.assertAlmostEqual(p['resource_commitment_mean'], 2/13)
        self.assertAlmostEqual(p['resource_commitment_std'], 2/13)
        self.assertAlmostEqual(p['action_delta_mean'], 7/18)
        self.assertAlmostEqual(p['action_delta_std'], math.sqrt(2)/18)
        self.assertEqual((p['previous_h_token'], p['recent_delta_mean'], p['recent_delta_std']), (1, 2/3, 0))
        self.assertEqual(before, (tuple(state.cursors), tuple(state.machine_ready), tuple(h.recent)))

    def test_tsp_hand_given_snapshots_and_degenerate_values(self):
        d = np.array([[0, 1, 2, 3], [1, 0, 4, 5], [2, 4, 0, 6], [3, 5, 6, 0]], dtype=float)
        sensor, h = TSPSensors(d), s.History(3, 2)
        initial = sensor.extract([0], [1, 2, 3], h)
        self.assertEqual(initial['legal_action_count'], 3)
        self.assertAlmostEqual(initial['remaining_demand_mean'], 1/3)
        self.assertEqual(initial['resource_commitment_std'], 0)
        h.commit(0, 1/3)
        p = sensor.extract([0, 2], [1, 3], h)
        self.assertAlmostEqual(p['remaining_demand_mean'], 1/3)
        self.assertAlmostEqual(p['remaining_demand_std'], 1/6)
        self.assertEqual((p['resource_commitment_mean'], p['resource_commitment_std']), (0.25, 0.25))
        self.assertAlmostEqual(p['action_delta_mean'], 5/6)
        self.assertAlmostEqual(p['action_delta_std'], 1/6)
        h.commit(1, 1)
        p = sensor.extract([0, 2, 3], [1], h)
        self.assertEqual(p['legal_action_count'], 1)
        self.assertEqual(p['remaining_demand_std'], 0)
        self.assertTrue(p['availability']['remaining_demand_std'])
        self.assertEqual(p['action_delta_std'], 0)
        self.assertAlmostEqual(p['resource_commitment_mean'], 2/4)
        self.assertEqual(d[0, 2], 2)  # no mutation

    def test_obp_only_current_item_and_opened_bins(self):
        h = s.History(5, 2)
        p, actions = obp(4, [], 10, h)
        self.assertEqual(actions, (0,))
        self.assertEqual(p['remaining_demand_mean'], 0.4)
        self.assertEqual(p['remaining_demand_std'], 0)
        self.assertTrue(p['availability']['remaining_demand_std'])
        self.assertIsNone(p['resource_commitment_mean'])
        self.assertFalse(p['availability']['resource_commitment_std'])
        self.assertEqual((p['action_delta_mean'], p['action_delta_std']), (1, 0))
        h.commit(1, 1)
        p, actions = obp(3, [4], 10, h)
        self.assertEqual(actions, (0,))
        self.assertEqual((p['action_delta_mean'], p['action_delta_std']), (0, 0))
        self.assertEqual(p['resource_commitment_mean'], 0.4)
        self.assertTrue(p['availability']['resource_commitment_std'])
        h.commit(0, 0)
        p, actions = obp(4, [7], 10, h)
        self.assertEqual(actions, (1,))
        self.assertEqual((p['recent_delta_mean'], p['recent_delta_std']), (0.5, 0.5))
        self.assertEqual(legal_actions(3, [7, 6, 10], 10), (0, 1))
        self.assertEqual(legal_actions(10, [10], 10), (1,))

    def test_window_uses_last_ten_actual_commits_no_padding(self):
        h = s.History(20, 2)
        for i in range(12):
            h.commit(i % 2, i / 20)
        p = s.observe('fjsp', history=h, demands=[1], commitments=[0], action_deltas=[0])
        self.assertEqual(p['history_count'], 12)
        self.assertEqual(p['recent_history_count'], 10)
        self.assertAlmostEqual(p['recent_delta_mean'], sum(range(2, 12))/200)
        self.assertEqual(p['previous_h_token'], 1)
        self.assertEqual(p['remaining_demand_std'], 0)
        with self.assertRaises(TypeError):
            p['action_delta_mean'] = 3
        with self.assertRaises(TypeError):
            p['availability']['action_delta_mean'] = False
        with self.assertRaises(ValueError):
            s.History(2, 2, window=3)
        terminal = s.History(1, 2)
        terminal.commit(0, 0)
        with self.assertRaises(ValueError):
            s.observe('fjsp', history=terminal, demands=[1], commitments=[0], action_deltas=[0])

    def test_packet_invalid_values_and_missing_are_different(self):
        p = plain(packet())
        for field, value in [('action_delta_mean', float('nan')), ('legal_action_count', True),
                             ('resource_commitment_mean', None), ('spec_sha256', 'old'),
                             ('window', 3), ('previous_h_token', 0)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                s.validate_packet({**p, field: value}, 2)
        wrong = plain(packet('tsp', 1))
        wrong['availability']['action_delta_std'] = False
        with self.assertRaises(ValueError):
            s.validate_packet(wrong, 2)
        for bad in (float('inf'), float('nan'), -1, True, 1.1):
            with self.assertRaises(ValueError):
                s.observe('fjsp', history=s.History(2, 2), demands=[bad], commitments=[0], action_deltas=[0])
        for item, used, capacity in [(0, [], 10), (11, [], 10), (1, [0], 10), (1, [], 0)]:
            with self.assertRaises(ValueError):
                legal_actions(item, used, capacity)

    def test_router_literal_reads_masks_actual_reads_and_version_rejection(self):
        code = '''def use_heuristics(state):
    if state["availability"]["recent_delta_mean"]:
        if state["recent_delta_mean"] > 0.1:
            return 1
    return 0
'''
        c = u.validate(code, member_count=2)
        self.assertEqual(u.checked(asdict(c), 2), c)
        reads = Counter()
        fn = u.compile_candidate(c, 2, reads=reads)
        self.assertEqual(fn(packet()), 0)
        self.assertNotIn('recent_delta_mean', reads)
        self.assertEqual(reads['availability.recent_delta_mean'], 1)
        self.assertEqual(fn(packet(count=2)), 1)
        self.assertEqual(reads['recent_delta_mean'], 1)
        inspected = u.inspect_reads(code, 2)
        self.assertEqual(inspected['value_fields'], ['recent_delta_mean'])
        self.assertEqual(inspected['availability_fields'], ['recent_delta_mean'])
        for field in ('usage_fraction', 'action_breadth_fraction', 'schema_id', 'problem_id', 'spec_sha256', 'missing_reason'):
            with self.assertRaises(u.CandidateError):
                u.validate(f'def use_heuristics(state):\n return state["{field}"]', member_count=2)
        for expression in ('True', '0.0', '-1', '2', 'None'):
            bad = u.compile_candidate(u.validate('def use_heuristics(state):\n return ' + expression, member_count=2), 2)
            with self.assertRaises(ValueError):
                bad(packet())
        for body in ('return state.__class__', 'return state["recent_delta_mean"][0]',
                     'return state["availability"]["nonexistent"]', 'return state["legal_action_count" + ""]',
                     'x = state\n    return 0', 'state["legal_action_count"] = 0\n    return 0',
                     'return __import__("os")', 'while True:\n        pass\n    return 0',
                     'return (0, (1,0))', 'return [0][0]', 'return 10 ** 100000'):
            with self.subTest(body=body), self.assertRaises(u.CandidateError):
                u.validate('def use_heuristics(state):\n    ' + body + '\n', member_count=2)
        with self.assertRaises(old.CandidateError):
            old.checked(asdict(c), 2)
        oldc = old.validate('def use_heuristics(state):\n return 0', member_count=2)
        with self.assertRaises(u.CandidateError):
            u.checked(asdict(oldc), 2)
        self.assertNotEqual(c.key, oldc.key)
        # Independently reconstruct the preexisting v1 key, not an A-key alias.
        from heuristic_design.core.constructive_state import SPEC_SHA256 as oldspec
        self.assertEqual(oldc.key, digest({'abi': 'pure-routing-state-v1', 'spec': oldspec,
            'members': 2, 'ast': ast.dump(ast.parse(oldc.code), include_attributes=False)}))
        self.assertEqual(old.compile_candidate(oldc, 2)({}), 0)
        reparsed = u.parse('A selector.\n```python\n' + c.code.rstrip() + '\n```', 2)
        self.assertEqual(reparsed.key, c.key)

    def test_prompt_and_cache_binding_align_with_new_contract(self):
        c = u.validate('def use_heuristics(state):\n return 0', member_count=2)
        for problem in s.PROBLEMS:
            prompt = u.build_prompt(problem, {'operator': 'MUTATE'},
                [{'id': 'original-parent', 'candidate': asdict(c)}], [{'id': 'H0'}, {'id': 'H1'}])
            for key in (*s.FIELDS, u.ABI, s.SPEC_SHA256, 'MINIMIZE', 'original-parent', c.code):
                # Code is serialized with literal newlines escaped by JSON.
                self.assertIn(json.dumps(c.code)[1:-1] if key == c.code else key, prompt)
            self.assertNotIn('Fitness is minus', prompt)
        args = dict(problem_id='tsp', state_schema=s.schema_id('tsp'), policy_sha256=c.key,
                    h_order=['h0', 'h1'], data_order=['future-train'], reference_sha256='frozen-lkh',
                    solve_seed=501, u_interface=u.ABI, action_schema='next-city', objective='relative-gap-min',
                    normalization=s.SPEC_SHA256, tie_rule='smallest-city', evaluator_sha256='new-evaluator')
        binding = make_binding(**args)
        self.assertTrue(assert_same_binding(binding, binding))
        changed = make_binding(**{**args, 'reference_sha256': 'different-lkh'})
        with self.assertRaises(ValueError):
            assert_same_binding(binding, changed)
        for mismatch in ({'u_interface': old.ABI}, {'normalization': 'old-B'}, {'objective': '-Cmax/LB'}):
            with self.assertRaises(ValueError):
                make_binding(**{**args, **mismatch})
        self.assertAlmostEqual(s.score_final_cost(120, 100), 0.2)
        for ref in (None, 0, -1, float('nan')):
            with self.assertRaises(ValueError):
                s.score_final_cost(120, ref)

    def test_new_result_and_entry_signatures_import_without_solving(self):
        from heuristic_design.problems.fjsp.routing import StateAResult as FJSPResult, construct_state_a as fjsp_entry
        from heuristic_design.problems.tsp.routing import StateAResult as TSPResult, construct_state_a as tsp_entry
        from heuristic_design.problems.obp.state_a import OnlineSession
        for result in (FJSPResult, TSPResult):
            signature = inspect.signature(result)
            self.assertEqual(signature.parameters['score_direction'].default, 'min')
            self.assertIs(signature.parameters['reference'].default, inspect.Parameter.empty)
        self.assertIn('usage', inspect.signature(fjsp_entry).parameters)
        self.assertIs(inspect.signature(tsp_entry).parameters['reference'].default, inspect.Parameter.empty)
        self.assertEqual(tuple(inspect.signature(OnlineSession.step).parameters), ('self', 'current_item', 'heuristics', 'usage'))

    def test_pure_selection_host_source_has_only_selected_h_and_post_commit_history(self):
        for rel, target in [('code/heuristic_design/problems/fjsp/routing.py', 'construct'),
                            ('code/heuristic_design/problems/tsp/routing.py', 'construct'),
                            ('code/heuristic_design/problems/obp/state_a.py', 'step')]:
            tree = ast.parse((ROOT / rel).read_text())
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == target)
            h_calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Subscript)
                       and isinstance(n.func.value, ast.Name) and n.func.value.id == 'members']
            self.assertEqual(len(h_calls), 1)
            self.assertIsInstance(h_calls[0].func.slice, ast.Name)
            self.assertEqual(h_calls[0].func.slice.id, 'member')
            usage = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'usage']
            self.assertEqual(len(usage), 1)
            commits = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'commit']
            self.assertEqual(len(commits), 1)
            self.assertLess(usage[0].lineno, h_calls[0].lineno)
            self.assertLess(h_calls[0].lineno, commits[0].lineno)
            # This is source evidence, not a solver execution or performance test.


if __name__ == '__main__':
    unittest.main()
