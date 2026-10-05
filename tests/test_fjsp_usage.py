"""Behavioral checks for the explicitly versioned offline Tier2 prototype."""

from dataclasses import FrozenInstanceError, replace
import math
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import Mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# Demo rules live in this repository's experiment namespace.
sys.path.insert(0, str(ROOT))

from experiments.tier2.offline_v1.run_demo import DEMO_H, constant_u, state_u
from fjsp_usage.offline_v1 import (
    InvalidSelectionError, StateSummary, construct_usage_schedule,
)
from llm4ad.task.optimization.fjsp_set import (
    FJSPSetEvaluation, construct_schedule, load_instance, validate_schedule,
)
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation


class FJSPUsageTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_instance(ROOT / 'experiments/tier2/offline_v1/tiny.fjsp')

    def test_one_selector_call_then_all_actions_use_only_selected_rule(self):
        events = []
        states = []

        def selector(state):
            self.assertIsInstance(state, StateSummary)
            states.append(state)
            selected = state_u(state)
            events.append(('U', state.step, selected))
            return selected

        def observed_rule(member):
            def rule(*features):
                self.assertEqual(len(features), 7)
                self.assertFalse(any(isinstance(value, StateSummary) for value in features))
                events.append(('h', states[-1].step, member))
                return DEMO_H[member](*features)
            return rule

        result = construct_usage_schedule(
            self.instance, tuple(observed_rule(i) for i in range(2)), selector)
        self.assertEqual(result.selected_members, (1, 0, 1))
        # Independently known counts of legal pairs for this tiny schedule.
        expected = []
        for step, (member, count) in enumerate(zip((1, 0, 1), (4, 4, 2))):
            expected.append(('U', step, member))
            expected.extend([('h', step, member)] * count)
        self.assertEqual(events, expected)
        self.assertEqual(len(states), self.instance.operation_count)
        self.assertEqual(states, [
            StateSummary(0, 3, (2, 1), (4, 2), (0, 0), (0, 0), 4),
            StateSummary(1, 3, (1, 1), (2, 2), (2, 0), (0, 2), 4),
            StateSummary(2, 3, (1, 0), (2, 0), (2, 2), (2, 2), 2),
        ])
        with self.assertRaises(FrozenInstanceError):
            states[0].step = 99
        with self.assertRaises(TypeError):
            states[0].machine_ready_times[0] = 99
        validate_schedule(self.instance, result.schedule)
        self.assertEqual((result.schedule.makespan, result.score), (4, -1.0))

    def test_constant_selector_matches_tier1_full_schedule_features_and_score(self):
        # Diverse synthetic instances exercise remaining work, ties, exhausted
        # jobs and differing machine alternatives without touching dataset splits.
        rng = random.Random(1234)
        instances = [self.instance]
        for i in range(20):
            machines = rng.randint(1, 4)
            jobs = tuple(tuple(Operation(tuple(sorted(
                (m, rng.randint(1, 9)) for m in rng.sample(
                    range(machines), rng.randint(1, machines)))))
                for _ in range(rng.randint(1, 4))) for _ in range(rng.randint(1, 4)))
            instances.append(FJSPInstance(f'synthetic-{i}', machines, jobs))
        for instance in instances:
            for member, rule in enumerate(DEMO_H):
                with self.subTest(instance=instance.name, member=member):
                    original_features, usage_features = [], []

                    def original(*features):
                        original_features.append(features)
                        return rule(*features)

                    def observed(*features):
                        usage_features.append(features)
                        return rule(*features)

                    unused = Mock(side_effect=AssertionError('unselected rule called'))
                    members = [unused, unused]
                    members[member] = observed
                    result = construct_usage_schedule(instance, members, lambda state: member)
                    reference = construct_schedule(instance, original)
                    self.assertEqual(result.schedule, reference)
                    self.assertEqual(usage_features, original_features)
                    self.assertEqual(result.selected_members, (member,) * instance.operation_count)
                    self.assertEqual(result.score,
                                     FJSPSetEvaluation.score_makespan(instance, reference.makespan))
                    unused.assert_not_called()

    def test_demo_selectors_are_deterministic_and_state_sensitive(self):
        state = StateSummary(0, 3, (2, 1), (4, 2), (0, 0), (0, 0), 4)
        self.assertEqual(state_u(state), 1)
        self.assertEqual(state_u(replace(state, machine_ready_times=(0, 2))), 0)
        for selector in (constant_u, state_u):
            first = construct_usage_schedule(self.instance, DEMO_H, selector)
            self.assertEqual(first, construct_usage_schedule(self.instance, DEMO_H, selector))
        fixed = construct_usage_schedule(self.instance, DEMO_H, constant_u)
        self.assertEqual(fixed.selected_members, (0, 0, 0))
        self.assertEqual((fixed.schedule.makespan, fixed.score), (4, -1.0))

    def test_invalid_ids_rejected_before_scoring_without_retry(self):
        class IntSubclass(int):
            pass

        for bad in (True, False, -1, 2, 100, 0.0, '0', None, [], {},
                    math.nan, np.int64(0), IntSubclass(0)):
            with self.subTest(value=repr(bad)):
                selector = Mock(return_value=bad)
                rule = Mock(return_value=0.0)
                with self.assertRaisesRegex(InvalidSelectionError, 'built-in int'):
                    construct_usage_schedule(self.instance, (rule, rule), selector)
                selector.assert_called_once()
                rule.assert_not_called()

    def test_selector_exception_rejected_with_cause_and_no_fallback(self):
        error = RuntimeError('broken U')
        selector = Mock(side_effect=error)
        rule = Mock(return_value=0.0)
        with self.assertRaises(InvalidSelectionError) as caught:
            construct_usage_schedule(self.instance, (rule,), selector)
        self.assertIs(caught.exception.__cause__, error)
        selector.assert_called_once()
        rule.assert_not_called()

    def test_later_invalid_selection_is_also_rejected(self):
        selector = Mock(side_effect=[0, True])
        rule = Mock(wraps=DEMO_H[0])
        with self.assertRaisesRegex(InvalidSelectionError, 'step 1'):
            construct_usage_schedule(self.instance, (rule,), selector)
        self.assertEqual(selector.call_count, 2)
        self.assertEqual(rule.call_count, 4)

    def test_rule_validation_and_ties_preserve_tier1_contract(self):
        for bad in (True, math.nan, math.inf, '1', [1], np.array([1.0])):
            with self.subTest(value=repr(bad)), self.assertRaises(ValueError):
                construct_usage_schedule(self.instance, (lambda *args: bad,), constant_u)
        broken = Mock(side_effect=RuntimeError('broken h'))
        with self.assertRaisesRegex(RuntimeError, 'broken h'):
            construct_usage_schedule(self.instance, (broken,), constant_u)
        tied = lambda *args: 0.0
        result = construct_usage_schedule(self.instance, (tied,), constant_u)
        self.assertEqual(result.schedule, construct_schedule(self.instance, tied))
        first = result.schedule.operations[0]
        self.assertEqual((first.job, first.operation, first.machine), (0, 0, 0))

    def test_invalid_h_rejected_before_u(self):
        for members in ((), (None,), (DEMO_H[0], 1)):
            selector = Mock(return_value=0)
            with self.assertRaises(ValueError):
                construct_usage_schedule(self.instance, members, selector)
            selector.assert_not_called()


if __name__ == '__main__':
    unittest.main()
