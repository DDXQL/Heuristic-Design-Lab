"""Synthetic lifecycle/identity mocks ONLY; no instances, U, network or solves."""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from fjsp_usage.research.protocol import digest
from tools.b1_timeout_boundary import classify_boundary, collect_with_lifecycle


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        modules = {'synthetic_only': {'loaded_functions': {'mock': 'abc'}}}
        self.witness = {'pid': 123, 'modules': modules, 'identity': digest(modules)}
        self.files = {'synthetic_only.py': 'SYNTHETIC-NOT-REAL-SOURCE'}
        self.kw = dict(before=self.witness, after=None, expected_identity=digest(modules),
            expected_files=self.files, start_files=self.files, end_files=self.files,
            lifecycle={'status': 'terminal', 'pid': 123, 'alive': False, 'exitcode': -15,
                       'trigger': 'parent_poll_timeout', 'deadline_seconds': 15,
                       'cleanup': ['join_0.05', 'terminate']})
        self.timeout = {'valid': False, 'fitness': None, 'error_type': 'Timeout',
                        'error': 'whole-instance deadline exceeded', 'failed_instance': 'MOCK'}

    def classify(self, result=None, **changes):
        return classify_boundary(result or self.timeout, **dict(self.kw, **changes))

    def test_confirmed_timeout_is_invalid_never_prefix_fitness(self):
        outcome = self.classify()
        self.assertEqual(outcome['decision'], 'candidate_invalid_continue')
        self.assertIsNone(outcome['fitness'])
        self.assertFalse(outcome['prefix_quality_accepted'])
        self.assertIn('unavailable', outcome['end_loaded_identity'])

    def test_historical_missing_lifecycle_still_stops(self):
        self.assertEqual(self.classify(lifecycle=None)['reason'], 'termination_unknown')

    def test_normal_completion_missing_after_stops(self):
        life = dict(self.kw['lifecycle'], exitcode=0, trigger=None)
        self.assertEqual(self.classify({'valid': True, 'fitness': -2}, lifecycle=life)['decision'], 'stop')

    def test_identity_mismatch_stops_even_if_timeout(self):
        after = dict(self.witness, identity='WRONG')
        self.assertEqual(self.classify(after=after)['reason'], 'child_end_identity_mismatch')

    def test_changed_or_incomplete_manifest_stops(self):
        for change in ({'end_files': {}}, {'start_files': {'other': 'x'}}):
            self.assertEqual(self.classify(**change)['decision'], 'stop')

    def test_live_wrong_pid_unknown_exit_and_started_receipt_stop(self):
        for change in ({'alive': True}, {'pid': 321}, {'exitcode': None}, {'status': 'started'}):
            self.assertEqual(self.classify(lifecycle=dict(self.kw['lifecycle'], **change))['decision'], 'stop')

    def test_unexpected_exit_or_timeout_without_termination_stops(self):
        for change in ({'exitcode': 1}, {'exitcode': 0}, {'cleanup': []}, {'deadline_seconds': 16}):
            self.assertEqual(self.classify(lifecycle=dict(self.kw['lifecycle'], **change))['decision'], 'stop')

    def test_worker_failure_and_forged_before_stop(self):
        self.assertEqual(self.classify(worker_failure=True)['decision'], 'stop')
        before = dict(self.witness, modules={'changed': True})
        self.assertEqual(self.classify(before=before)['decision'], 'stop')

    def test_complete_matching_identity_delegates_original_result_check(self):
        life = dict(self.kw['lifecycle'], exitcode=0, trigger=None)
        result = self.classify({'valid': True, 'fitness': -2}, after=self.witness, lifecycle=life)
        self.assertEqual(result['decision'], 'original_result_checks_required')

    def context(self, alive, exitcode, *, readable=False, row=None):
        worker = Mock(pid=123, exitcode=exitcode)
        worker.is_alive.side_effect = alive
        receive, send = Mock(), Mock()
        receive.poll.return_value = readable
        receive.recv.return_value = row
        context = Mock()
        context.Pipe.return_value = (receive, send)
        context.Process.return_value = worker
        return context, worker, receive

    def collect(self, context, persist):
        return collect_with_lifecycle(context, None, None, (), (), ('MOCK',), 15,
                                      (0, 1), persist, clock=lambda: 1.0)

    def test_collector_records_termination_and_does_not_repeat(self):
        context, worker, receive = self.context([True, False, False], -15)
        records = []
        rows, failure, life = self.collect(context, lambda x: records.append(deepcopy(x)))
        self.assertEqual(rows, []); self.assertEqual(failure['error_type'], 'Timeout')
        self.assertEqual([r['status'] for r in records], ['started', 'terminal'])
        worker.start.assert_called_once(); worker.terminate.assert_called_once()
        worker.kill.assert_not_called(); receive.poll.assert_called_once_with(15)
        self.assertFalse(life['alive'])

    def test_kill_escalation_preserves_unknown_if_still_alive(self):
        context, worker, _ = self.context([True, True, True], None)
        _, _, life = self.collect(context, lambda _: None)
        worker.kill.assert_called_once(); self.assertTrue(life['alive'])
        self.assertEqual(self.classify(lifecycle=life)['decision'], 'stop')

    def test_persistence_failure_does_not_leave_worker_unmanaged(self):
        context, worker, _ = self.context([True, False, False], -15)
        with self.assertRaises(OSError):
            self.collect(context, Mock(side_effect=OSError('MOCK disk failure')))
        worker.terminate.assert_called_once()

    def test_eof_is_not_timeout(self):
        context, _, receive = self.context([False, False, False], 0, readable=True)
        receive.recv.side_effect = EOFError
        _, failure, life = self.collect(context, lambda _: None)
        outcome = self.classify(failure, after=self.witness, lifecycle=life)
        self.assertEqual(outcome['decision'], 'stop')


if __name__ == '__main__':
    unittest.main()
