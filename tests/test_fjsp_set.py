"""Task-level legality and score-contract checks; no LLM required."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from llm4ad.task.optimization.fjsp_set import (
    FJSPSetEvaluation, construct_schedule, load_instance, validate_schedule,
)
from llm4ad.task.optimization.fjsp_set.scheduler import Schedule, ScheduledOperation


SAMPLE = '''NAME: tiny
TYPE: FJSP
JOBS: 2
MACHINES: 2
JOB_SECTION
2 2 1 3 2 2 2 1 2 2 4
1 2 1 2 2 3
'''


class FJSPSetTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / 'tiny.fjsp'
        self.path.write_text(SAMPLE, encoding='utf-8')
        self.instance = load_instance(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_known_schedule_and_score_direction(self):
        eft = lambda p, r, n, j, m, s, f: -f
        spt = lambda p, r, n, j, m, s, f: -p
        eft_schedule = construct_schedule(self.instance, eft)
        spt_schedule = construct_schedule(self.instance, spt)
        self.assertEqual((eft_schedule.makespan, spt_schedule.makespan), (4, 6))
        self.assertGreater(FJSPSetEvaluation.score_makespan(self.instance, 4),
                           FJSPSetEvaluation.score_makespan(self.instance, 6))
        evaluation = FJSPSetEvaluation([self.path])
        self.assertEqual(evaluation.evaluate(eft), [-1.0])
        self.assertEqual(evaluation.evaluate(spt), [-1.5])

    def test_invalid_priority_and_schedule_rejected(self):
        for bad in (lambda *args: math.nan, lambda *args: math.inf,
                    lambda *args: [1, 2], lambda *args: np.array([1.0]),
                    lambda *args: '1.0', lambda *args: True):
            with self.assertRaises(ValueError):
                construct_schedule(self.instance, bad)
        valid = construct_schedule(self.instance, lambda p, r, n, j, m, s, f: -f)
        first = valid.operations[0]
        tampered = Schedule((ScheduledOperation(first.job, first.operation, first.machine,
                                               first.start, first.end + 1),) + valid.operations[1:],
                            valid.makespan)
        with self.assertRaises(ValueError):
            validate_schedule(self.instance, tampered)
        evaluation = FJSPSetEvaluation([self.path])
        self.assertIsNone(evaluation.evaluate_program('', lambda *args: math.nan))

    def test_ties_use_job_then_machine_order(self):
        schedule = construct_schedule(self.instance, lambda *args: 0.0)
        first = schedule.operations[0]
        self.assertEqual((first.job, first.operation, first.machine), (0, 0, 0))

    def test_malformed_input_rejected(self):
        self.path.write_text(SAMPLE.replace('MACHINES: 2', 'MACHINES: 1'), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_instance(self.path)


if __name__ == '__main__':
    unittest.main()
