"""Focused pre-search checks: no candidate generation, solving or network."""
from dataclasses import asdict
import threading
import unittest
from unittest.mock import patch

from heuristic_design.core import evolution_v1 as e, routing
from heuristic_design.llm import routing_transport as transport


class Tests(unittest.TestCase):
    def test_task_pool_preserves_overlapping_intervals_and_errors(self):
        barrier = threading.Barrier(2)
        def task(row):
            barrier.wait(timeout=3)
            if row['id'] == 'bad':
                raise ValueError('expected task failure')
            return row['id']
        rows = e._batch(task, [{'id':'good'}, {'id':'bad'}], 2)
        self.assertEqual(rows['good']['value'], 'good')
        self.assertFalse(rows['bad']['ok'])
        self.assertEqual(rows['bad']['error_type'], 'ValueError')
        timings = [r['timing'] for r in rows.values()]
        self.assertLess(max(r['started_monotonic'] for r in timings),
                        min(r['finished_monotonic'] for r in timings))

    def test_fjsp_material_and_original_parents_in_all_operator_prompts(self):
        candidate = asdict(routing.validate('def use_heuristics(state):\n    return 0\n'))
        parent = {'id':'frozen-original', 'candidate':candidate, 'fitness':-123.456789}
        for operation in ('INIT', 'CROSS', 'MUTATE'):
            parents = [] if operation == 'INIT' else [parent]
            text = routing.build_prompt('fjsp', {'operator':operation}, parents,
                                        [{'id':f'H{i}'} for i in range(10)])
            for required in ('makespan Cmax', '-Cmax/LB', 'no rounding',
                             'D=Q', 'B=sum(max processing per operation)',
                             'remaining_work', 'no type annotations', 'No MIX'):
                self.assertIn(required, text)
            if parents:
                self.assertIn(parent['id'], text)
                self.assertIn(candidate['key'], text)
            self.assertNotIn(str(parent['fitness']), text)

    def test_failed_wire_keeps_send_confirmation_usage_and_redacted_metadata(self):
        class Failure(RuntimeError):
            usage = {'input_tokens':17, 'output_tokens':2}
            metadata = {'http_status':429, 'authorization':'must-not-escape'}
        class Wire:
            def __init__(self, client): pass
            def preflight(self, prompt): pass
            def dispatch(self, *args, on_sent, **kwargs):
                on_sent()
                raise Failure('rate limit')
            def redact(self, value): return value
            def redact_metadata(self, value):
                return {**value, 'authorization':'[REDACTED]'}
        with patch.object(transport, 'ClientConfig', return_value=object()), \
                patch.object(transport, 'JsonCandidateTransport', Wire):
            result = transport.generate({'request_key':'offline-check'}, 'no request',
                                        {'api_attempt_cap':8}, 10)
        self.assertTrue(result['sent'])
        self.assertIsInstance(result['wire_send_confirmed_at_unix'], float)
        self.assertEqual(result['usage'], Failure.usage)
        self.assertEqual(result['metadata']['http_status'], 429)
        self.assertNotIn('must-not-escape', str(result))


if __name__ == '__main__':
    unittest.main()
