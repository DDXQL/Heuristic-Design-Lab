"""Only local admission/recording checks; no train evaluation or new instance."""
from dataclasses import replace
from pathlib import Path
import unittest

from fjsp_usage.research.candidates import compile_candidate, validate_code
from fjsp_usage.research.protocol import digest
from fjsp_usage.usage_v2.execution import decode_output, construct_usage_schedule
from llm4ad.task.optimization.fjsp_set import load_instance
from tools.calibrate_fixed_mixtures import grid, PAIRS, WEIGHTS
from tools.usage_mechanism_ablation import physical_schedule, evaluate_with_schedules

ROOT = Path(__file__).resolve().parents[1]


class FixedGridTests(unittest.TestCase):
    def test_exact_frozen_grid_and_actual_host_decoding(self):
        rows = grid()
        self.assertEqual(len({r['candidate']['key'] for r in rows}), 12)
        self.assertEqual([(tuple(r['pair']), tuple(r['weights'])) for r in rows],
                         [(p, w) for p in PAIRS for w in WEIGHTS])
        for row in rows:
            from fjsp_usage.research_real.assets import checked_candidate
            fn = compile_candidate(checked_candidate(row['candidate'], 'U'))
            outputs = [fn(*state) for state in ((0., 1., .1, .01, 0., 0., -1),
                       (.99, .1, .01, 0., .4, .2, 9))]
            self.assertEqual(outputs[0], outputs[1])
            decoded = decode_output(outputs[0], 10)
            self.assertEqual(decoded['mode'], 1)
            self.assertEqual(decoded['support'], tuple(row['pair']))
            for i, weight in zip(row['pair'], row['weights']):
                self.assertAlmostEqual(decoded['weights'][i], weight)
            self.assertEqual(decoded['dominant'], row['pair'][0 if row['weights'][0] >= .5 else 1])

    def test_recorded_physical_schedule_matches_unchanged_executor(self):
        from fjsp_usage.research_real.assets import checked_candidate
        candidate = checked_candidate(grid()[0]['candidate'], 'U')
        args = 'processing_time, remaining_work, remaining_operations, job_ready_time, machine_ready_time, earliest_start, earliest_finish'
        h = validate_code(f'def priority({args}):\n    return -earliest_finish\n', kind='h')
        members = (h,) * 10
        instance = load_instance(ROOT / 'experiments/tier2/offline_v1/tiny.fjsp')
        expected = construct_usage_schedule(instance, tuple(compile_candidate(x) for x in members),
                                            compile_candidate(candidate))
        result = evaluate_with_schedules(candidate, members, (instance,), ('existing-tiny-fixture',),
                                         timeout=5, diagnostics=False)
        self.assertTrue(result['valid'])
        row = result['instances'][0]
        self.assertEqual(row['captured_solves'], 2)
        self.assertEqual(row['physical_schedule'], physical_schedule(expected.schedule))
        self.assertEqual(row['physical_schedule_sha256'], digest(physical_schedule(expected.schedule)))
        self.assertEqual(row['single_h_calls'], list(expected.member_calls))
        self.assertEqual(row['single_h_calls'], row['deterministic_recheck_h_calls'])
        self.assertNotIn('diagnostic_evaluation_seconds', result)

    def test_physical_identity_ignores_commit_order_but_not_assignment(self):
        from llm4ad.task.optimization.fjsp_set.scheduler import Schedule, ScheduledOperation
        schedule = Schedule((ScheduledOperation(0, 0, 1, 0, 2), ScheduledOperation(1, 0, 0, 0, 3)), 3)
        reordered = replace(schedule, operations=tuple(reversed(schedule.operations)))
        changed = replace(schedule, operations=(replace(schedule.operations[0], machine=0), schedule.operations[1]))
        self.assertEqual(physical_schedule(schedule), physical_schedule(reordered))
        self.assertNotEqual(physical_schedule(schedule), physical_schedule(changed))


if __name__ == '__main__':
    unittest.main()
