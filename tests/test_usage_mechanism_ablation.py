"""Proportionate checks of deterministic interventions; no benchmark replay."""
from pathlib import Path
import unittest

from tools.usage_mechanism_ablation import transform, TARGETS, ARCHIVE
from fjsp_usage.research.candidates import compile_candidate, validate_code
from fjsp_usage.usage_v2 import VERSION
from fjsp_usage.usage_v2.execution import decode_output, construct_usage_schedule
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation

ARGS = 'progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic'


class InterventionTests(unittest.TestCase):
    def test_actual_sources_support_and_argmax_in_both_branches(self):
        states = [(p, .5, .2, ws, .4, ms, prev)
                  for p in (0., .4, .99) for ws, ms in ((.1, .3), (.3, .1))
                  for prev in (-1, 2, 4, 7, 9)]
        for target in TARGETS:
            path = ARCHIVE / (target.replace('/', '__') + '.py')
            code = path.read_text()
            original = compile_candidate(validate_code(code, interface_version=VERSION, member_count=10))
            equal = compile_candidate(transform(code, 'equal'))
            winner = compile_candidate(transform(code, 'winner'))
            for state in states:
                a, b, c = [decode_output(fn(*state), 10) for fn in (original, equal, winner)]
                self.assertEqual(b['support'], a['support'])
                self.assertEqual([b['weights'][i] for i in b['support']], [.5, .5])
                self.assertEqual(c['support'], (a['dominant'],))
            self.assertEqual(path.read_text(), code)

    def test_equal_tie_changes_history_and_winner_calls_only_selected_h(self):
        code = f'def use_heuristics({ARGS}):\n    return (1, (0.2, 0.8))\n'
        instance = FJSPInstance('two', 1, ((Operation(((0, 2),)), Operation(((0, 1),))),))
        for variant, dominant, expected in [('equal', 0, (2, 2)), ('winner', 1, (0, 2))]:
            fn = compile_candidate(transform(code, variant, size=2))
            seen = []
            def usage(*state):
                seen.append(state[-1])
                return fn(*state)
            result = construct_usage_schedule(instance, (lambda *a: -a[0], lambda *a: -a[0]), usage)
            self.assertEqual(seen, [-1, dominant])
            self.assertEqual(result.member_calls, expected)

    def test_zero_support_and_ties_do_not_create_a_new_member(self):
        code = f'def use_heuristics({ARGS}):\n    return (1, (0.7, 0.0, 0.7))\n'
        state = (0., .5, .2, .1, 0., 0., -1)
        equal = decode_output(compile_candidate(transform(code, 'equal', 3))(*state), 3)
        winner = decode_output(compile_candidate(transform(code, 'winner', 3))(*state), 3)
        self.assertEqual(equal['support'], (0, 2))
        self.assertEqual(winner['support'], (0,))

    def test_collision_and_wrong_original_mode(self):
        code = f'def use_heuristics({ARGS}):\n    ablationWeight0 = 0.2\n    return (1, (ablationWeight0, 0.8))\n'
        fn = compile_candidate(transform(code, 'equal', 2))
        self.assertEqual(fn(0., .5, .2, .1, 0., 0., -1), (1, (1., 1.)))
        with self.assertRaises(ValueError):
            transform(code.replace('(1, (', '(0, ('), 'equal', 2)


if __name__ == '__main__':
    unittest.main()
