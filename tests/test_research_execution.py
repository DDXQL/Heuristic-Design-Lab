"""Contracts for the versioned observer and restricted numerical execution."""

import sys
from pathlib import Path
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
sys.path.insert(0, str(ROOT))
from experiments.tier2.offline_v2.run_training_demo import DEMO_H, constant_u, state_u
from fjsp_usage.offline_v2 import construct_usage_schedule as original
from fjsp_usage.research.candidates import CandidateError, U_ARGS, H_ARGS, validate_code, parse_response
from fjsp_usage.research.runtime import evaluate
from fjsp_usage.research.scheduler import construct_usage_schedule
from fjsp_usage.research.viewer import write_replay
from llm4ad.task.optimization.fjsp_set import load_instance
from llm4ad.task.optimization.fjsp_set import construct_schedule
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation


def u(body, description='fixture'):
    return validate_code('def select_heuristic(' + ', '.join(U_ARGS) + '):\n' + body,
                         description=description)


def h(expression):
    return validate_code('def priority(' + ', '.join(H_ARGS) + '):\n    return ' + expression,
                         kind='h', description=expression)


class ResearchExecutionTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_instance(ROOT / 'experiments/tier2/offline_v1/tiny.fjsp')
        self.members = (h('-earliest_finish'), h('-processing_time'))

    def test_trace_equivalence_and_one_U_selected_h_per_step(self):
        trace, calls = [], []
        def selector(*args):
            calls.append(args)
            return state_u(*args)
        result = construct_usage_schedule(self.instance, DEMO_H, selector, trace=trace.append)
        self.assertEqual(result, original(self.instance, DEMO_H, state_u))
        self.assertEqual(len(calls), self.instance.operation_count)
        self.assertEqual([len(t['actions']) for t in trace], [4, 4, 2])
        for t, state in zip(trace, calls):
            self.assertEqual(tuple(t['state'].values()), state)
            for a in t['actions']:
                self.assertEqual(a['score'], -a['end'] if t['member_id'] == 0 else -a['processing_time'])
        bounded = []
        self.assertEqual(construct_usage_schedule(self.instance, DEMO_H, state_u,
                         trace=bounded.append, max_actions=1), result)
        self.assertTrue(all(t['actions_truncated'] for t in bounded))

    def test_ast_dedup_ignores_comments_docs_annotations_not_equal_scores(self):
        plain = u('    return 0')
        annotated = validate_code('def select_heuristic(' + ', '.join(
            a + ': ' + ('int' if i == 6 else 'float') for i, a in enumerate(U_ARGS))
            + ') -> int:\n    """different documentation"""\n    return 0 # comment')
        self.assertEqual(plain.key, annotated.key)
        self.assertNotEqual(plain.key, u('    return 1').key)

    def test_parser_and_resource_access_rejection(self):
        c = u('    return 0')
        self.assertEqual(parse_response('{Always use member zero.}\n```python\n'+c.code+'```').key, c.key)
        forbidden = ['    return open(0)', '    return progress.__class__',
                     '    import os\n    return 0', '    return eval(0)',
                     '    global x\n    return 0', '    return H(0)',
                     '    def helper():\n        return 0\n    return helper()',
                     '    return 9 ** previous_heuristic']
        for body in forbidden:
            with self.subTest(body=body), self.assertRaises(CandidateError):
                u(body)
        with self.assertRaises(CandidateError):
            parse_response('extra\n{description}\n```python\n'+c.code+'```')

    def test_full_train_or_invalid_and_illegal_returns(self):
        good = evaluate(u('    return 0'), self.members, (self.instance,), ('tiny',))
        self.assertTrue(good['valid'], good)
        self.assertEqual(good['fitness'], original(self.instance, DEMO_H, constant_u).score)
        for body in ('    return True', '    return 0.0', '    return -1',
                     '    return 2', '    return 1 / 0'):
            with self.subTest(body=body):
                result = evaluate(u(body), self.members, (self.instance,), ('tiny',))
                self.assertFalse(result['valid'])
                self.assertIsNone(result['fitness'])

    def test_constant_member_matches_frozen_schedule_and_failed_suffix_has_no_fitness(self):
        for member in (0, 1):
            result = construct_usage_schedule(self.instance, DEMO_H, lambda *args: member)
            self.assertEqual(result.schedule, construct_schedule(self.instance, DEMO_H[member]))
        single = FJSPInstance('single', 1, ((Operation(((0, 5),)),),))
        candidate = u('    return 0 if remaining_work_mean < 0.9 else 99')
        result = evaluate(candidate, self.members, (self.instance, single), ('tiny', 'single'))
        self.assertFalse(result['valid'])
        self.assertIsNone(result['fitness'])
        self.assertEqual(result['failed_instance'], 'single')
        self.assertEqual(len(result['instances']), 1)

    def test_replay_is_inert_and_contains_actual_schedule(self):
        import tempfile
        trace = []
        result = construct_usage_schedule(self.instance, DEMO_H, state_u, trace=trace.append)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'replay.html'
            write_replay(path, trace=trace, makespan=result.schedule.makespan,
                         score=result.score, instance='</script><script>bad()</script>')
            source = path.read_text()
            self.assertNotIn('</script><script>bad()', source)
            self.assertIn('\\u003c/script\\u003e', source)
            self.assertIn('"makespan": 4', source)
            self.assertNotIn('https://', source)

    def test_infinite_loop_is_killed_and_huge_integers_are_bounded(self):
        started = time.monotonic()
        result = evaluate(u('    while True:\n        pass\n    return 0'),
                          self.members, (self.instance,), ('tiny',), timeout=0.4)
        self.assertEqual(result['error_type'], 'Timeout')
        self.assertLess(time.monotonic() - started, 3)
        bomb = evaluate(u('    x = 999999999\n    while True:\n        x *= x\n    return 0'),
                        self.members, (self.instance,), ('tiny',))
        self.assertEqual(bomb['error_type'], 'InvalidSelectionError')

    def test_implicit_none_path_rejected_and_round_allocation_guard(self):
        with self.assertRaises(CandidateError):
            u('    if progress < 0.5:\n        return 0')
        result = evaluate(u('    return round(1, -999999999)'), self.members,
                          (self.instance,), ('tiny',))
        self.assertFalse(result['valid'])
        self.assertEqual(result['error_type'], 'InvalidSelectionError')


if __name__ == '__main__':
    unittest.main()
