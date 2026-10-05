"""V5 state semantics, scheduling contract and all-or-invalid train fitness."""

from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.tier2.offline_v2.run_training_demo import DEMO_H, constant_u, state_u
from fjsp_usage.offline_v2 import (
    InvalidSelectionError, StateFeatures, construct_usage_schedule, lower_bound_v5,
)
from fjsp_usage.training_v2 import TrainingEvaluation
from llm4ad.task.optimization.fjsp_set import construct_schedule, load_instance
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation


ASYMMETRIC = '''NAME: asymmetric
TYPE: FJSP
JOBS: 2
MACHINES: 3
JOB_SECTION
2 1 1 3 3 1 4 2 6 3 8
1 2 2 2 3 5
'''
FRACTIONAL_LB = '''NAME: fractional
TYPE: FJSP
JOBS: 3
MACHINES: 2
JOB_SECTION
1 1 1 1
1 1 1 1
1 1 1 1
'''


class V5SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.tiny = load_instance(ROOT / 'experiments/tier2/offline_v1/tiny.fjsp')
        self.asymmetric = FJSPInstance('asymmetric', 3, (
            (Operation(((0, 3),)), Operation(((0, 4), (1, 6), (2, 8)))),
            (Operation(((1, 2), (2, 5))),),
        ))

    def test_exact_state_values_fixed_T_C_and_population_membership(self):
        seen = []

        def selector(*values):
            self.assertEqual(len(values), 7)
            self.assertTrue(all(type(value) is float for value in values[:6]))
            self.assertIs(type(values[6]), int)
            seen.append(StateFeatures(*values))
            return 0

        result = construct_usage_schedule(self.asymmetric, DEMO_H, selector)
        # T=3+8+5=16, C=max(1,3)+2=5, initial candidate count=1+2=3.
        # EFT completes job 1 first. Its zero remaining work must be excluded.
        expected = [
            (0., 3/5, 9/32, 5/32, 0., 0., -1),
            (1/3, 1/5, 7/16, 0., 1/24, math.sqrt(2)/24, 0),
            (2/3, 3/5, 4/16, 0., 5/48, math.sqrt(14)/48, 0),
        ]
        self.assertEqual(len(seen), 3)  # no terminal invocation
        for actual, wanted in zip(seen, expected):
            for value, target in zip(actual, wanted):
                self.assertAlmostEqual(value, target)
        self.assertEqual(result.schedule.makespan, 7)

    def test_single_job_machine_population_std_zero(self):
        instance = FJSPInstance('single', 1, ((Operation(((0, 5),)),),))
        selector = Mock(return_value=0)
        construct_usage_schedule(instance, DEMO_H, selector)
        selector.assert_called_once_with(0., 1., 1., 0., 0., 0., -1)

    def test_time_rescaling_leaves_U_features_invariant(self):
        scaled = replace(self.asymmetric, jobs=tuple(tuple(
            Operation(tuple((m, p * 11) for m, p in op.alternatives)) for op in job)
            for job in self.asymmetric.jobs))
        traces = []
        for instance in (self.asymmetric, scaled):
            trace = []

            def selector(*values):
                trace.append(values)
                return 0

            construct_usage_schedule(instance, DEMO_H, selector)
            traces.append(trace)
        self.assertEqual(traces[0], traces[1])

    def test_call_order_selected_h_only_and_previous_member(self):
        events, states = [], []

        def selector(*values):
            states.append(values)
            member = state_u(*values)
            events.append(('U', member))
            return member

        def observed(member):
            def rule(*features):
                self.assertEqual(len(features), 7)
                # h sees raw per-action data; U sees only scalar summaries.
                self.assertIs(type(features[2]), int)
                events.append(('h', member))
                return DEMO_H[member](*features)
            return rule

        result = construct_usage_schedule(self.tiny, (observed(0), observed(1)), selector)
        expected = []
        for member, count in ((1, 4), (0, 4), (1, 2)):
            expected += [('U', member)] + [('h', member)] * count
        self.assertEqual(events, expected)
        self.assertEqual([values[6] for values in states], [-1, 1, 0])
        self.assertEqual(result.selected_members, (1, 0, 1))
        self.assertEqual((result.schedule.makespan, result.lower_bound, result.score), (4, 4., -1.))

    def test_constant_U_preserves_tier1_schedule_and_all_action_features(self):
        rng = random.Random(20261004)
        instances = [self.tiny, self.asymmetric]
        for index in range(20):
            machines = rng.randint(1, 4)
            jobs = tuple(tuple(Operation(tuple(sorted(
                (m, rng.randint(1, 9)) for m in rng.sample(
                    range(machines), rng.randint(1, machines)))))
                for _ in range(rng.randint(1, 4))) for _ in range(rng.randint(1, 4)))
            instances.append(FJSPInstance(f'synthetic-{index}', machines, jobs))
        for instance in instances:
            for member, rule in enumerate(DEMO_H):
                with self.subTest(instance=instance.name, member=member):
                    original = Mock(wraps=rule)
                    selected = Mock(wraps=rule)
                    unused = Mock(side_effect=AssertionError('unselected rule called'))
                    members = [unused, unused]
                    members[member] = selected
                    result = construct_usage_schedule(instance, members, lambda *values: member)
                    self.assertEqual(result.schedule, construct_schedule(instance, original))
                    self.assertEqual(selected.call_args_list, original.call_args_list)
                    self.assertEqual(result.selected_members, (member,) * instance.operation_count)
                    unused.assert_not_called()

    def test_invalid_ids_fail_before_any_scoring_without_retry(self):
        class IntSubclass(int):
            pass

        for bad in (True, False, -1, 2, 100, 0., '0', None, [], {}, math.nan,
                    np.int64(0), IntSubclass(0)):
            with self.subTest(value=repr(bad)):
                selector, rule = Mock(return_value=bad), Mock(return_value=0.)
                with self.assertRaisesRegex(InvalidSelectionError, 'built-in int'):
                    construct_usage_schedule(self.tiny, (rule, rule), selector)
                selector.assert_called_once()
                rule.assert_not_called()

    def test_exception_and_later_invalid_selection_do_not_fall_back(self):
        error = RuntimeError('broken U')
        selector, rule = Mock(side_effect=error), Mock(wraps=DEMO_H[0])
        with self.assertRaises(InvalidSelectionError) as caught:
            construct_usage_schedule(self.tiny, (rule,), selector)
        self.assertIs(caught.exception.__cause__, error)
        selector.assert_called_once()
        rule.assert_not_called()
        selector = Mock(side_effect=[0, True])
        with self.assertRaisesRegex(InvalidSelectionError, 'step 1'):
            construct_usage_schedule(self.tiny, (rule,), selector)
        self.assertEqual(selector.call_count, 2)
        self.assertEqual(rule.call_count, 4)

    def test_invalid_H_scores_and_stable_ties(self):
        for members in ((), (None,), (DEMO_H[0], 1)):
            selector = Mock(return_value=0)
            with self.assertRaises(ValueError):
                construct_usage_schedule(self.tiny, members, selector)
            selector.assert_not_called()
        for bad in (True, math.nan, math.inf, '1', [1], np.array([1.])):
            with self.subTest(score=repr(bad)), self.assertRaises(ValueError):
                construct_usage_schedule(self.tiny, (lambda *args: bad,), constant_u)
        tied = lambda *args: 0.
        result = construct_usage_schedule(self.tiny, (tied,), constant_u)
        self.assertEqual(result.schedule, construct_schedule(self.tiny, tied))

    def test_demo_U_deterministic_and_sensitive_to_summary(self):
        values = (0., 1., .3, .1, 0., 0., -1)
        self.assertEqual(state_u(*values), 1)
        self.assertEqual(state_u(*values[:5], .1, -1), 0)
        for selector in (constant_u, state_u):
            self.assertEqual(construct_usage_schedule(self.tiny, DEMO_H, selector),
                             construct_usage_schedule(self.tiny, DEMO_H, selector))


class TrainingV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        data = self.root / 'data'
        data.mkdir()
        texts = {'a.fjsp': ASYMMETRIC, 'b.fjsp': FRACTIONAL_LB}
        for name, content in texts.items():
            (data / name).write_text(content, encoding='utf-8')
        # Held-out files intentionally do not exist: neither may be opened.
        self.manifest = {
            'portable_root': 'data',
            'split': {'train': list(texts), 'validation': ['held_validation.fjsp'],
                      'test': ['held_test.fjsp']},
            'files': {name: {'sha256': hashlib.sha256(content.encode()).hexdigest()}
                      for name, content in texts.items()},
        }
        self.manifest_path = self.root / 'manifest.json'
        self.write_manifest()

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def evaluation(self):
        return TrainingEvaluation(self.manifest_path, project_root=self.root)

    def test_per_instance_scores_and_mean_of_ratios_on_train_only(self):
        with patch('fjsp_usage.training_v2.load_instance', wraps=load_instance) as loader:
            evaluation = self.evaluation()
        self.assertEqual([call.args[0].name for call in loader.call_args_list], ['a.fjsp', 'b.fjsp'])
        selector = Mock(wraps=constant_u)
        result = evaluation.evaluate(DEMO_H, selector)
        self.assertTrue(result.valid)
        self.assertEqual(result.total_instances, 2)
        self.assertEqual([(r.makespan, r.lower_bound, r.score) for r in result.instances],
                         [(7, 7., -1.), (3, 1.5, -2.)])
        self.assertEqual(result.mean_training_fitness, -1.5)
        # Explicitly distinguish mean of ratios from a pooled ratio.
        self.assertNotAlmostEqual(result.mean_training_fitness, -10/8.5)
        self.assertEqual(selector.call_count, 6)
        self.assertEqual(selector.call_args_list[0].args[6], -1)
        self.assertEqual(selector.call_args_list[3].args[6], -1)
        fractional = evaluation.instances[1]
        self.assertEqual(lower_bound_v5(fractional), 1.5)
        self.assertEqual(fractional.lower_bound, 2)  # frozen Tier1 is untouched

    def test_any_failed_instance_invalidates_entire_U_not_successful_subset(self):
        evaluation = self.evaluation()
        # Second instance's initial candidate ratio is one; first's is 3/5.
        def invalid_on_second(progress, candidate_pair_ratio, *rest):
            return True if progress == 0. and candidate_pair_ratio == 1. else 0

        result = evaluation.evaluate(DEMO_H, invalid_on_second)
        self.assertFalse(result.valid)
        self.assertIsNone(result.mean_training_fitness)
        self.assertEqual(result.failed_instance, 'b.fjsp')
        self.assertEqual(len(result.instances), 1)
        self.assertIn('InvalidSelectionError', result.error)

    def test_U_and_h_exceptions_and_infeasibility_invalidate_batch(self):
        evaluation = self.evaluation()
        for error in (RuntimeError('broken'), TimeoutError('caller timeout')):
            result = evaluation.evaluate(DEMO_H, Mock(side_effect=error))
            self.assertFalse(result.valid)
            self.assertIsNone(result.mean_training_fitness)
            self.assertEqual(result.instances, ())
            self.assertIn(type(error).__name__, result.error)
        result = evaluation.evaluate((Mock(side_effect=RuntimeError('broken h')),), constant_u)
        self.assertFalse(result.valid)
        with patch('fjsp_usage.offline_v2.validate_schedule', side_effect=ValueError('infeasible')):
            result = evaluation.evaluate(DEMO_H, constant_u)
        self.assertFalse(result.valid)
        self.assertIsNone(result.mean_training_fitness)

    def test_empty_duplicate_overlap_and_path_escape_rejected_before_loading(self):
        cases = [
            {'train': []}, {'train': ['a.fjsp', './a.fjsp']},
            {'validation': ['a.fjsp']}, {'test': ['a.fjsp']},
            {'test': ['held_validation.fjsp']}, {'train': ['../escape.fjsp']},
        ]
        original = self.manifest['split'].copy()
        for changes in cases:
            with self.subTest(changes=changes):
                self.manifest['split'] = {**original, **changes}
                self.write_manifest()
                with patch('fjsp_usage.training_v2.load_instance') as loader:
                    with self.assertRaises(ValueError):
                        self.evaluation()
                    loader.assert_not_called()

    def test_training_hash_mismatch_is_not_silently_accepted(self):
        (self.root / 'data/a.fjsp').write_text(ASYMMETRIC + '\n')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.evaluation()


if __name__ == '__main__':
    unittest.main()
