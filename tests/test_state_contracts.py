"""Pure metadata/identity tests: no API, solve or data generation."""
import copy
import unittest
from heuristic_design.core.state_contracts import (
    FJSP_LEGACY, TSP_LEGACY, COMMON_DRAFT, legacy_packet,
    require_executable_schema, make_binding, assert_same_binding)

class Tests(unittest.TestCase):
    def binding(self, **changes):
        values = dict(problem_id='fjsp', state_schema=FJSP_LEGACY.schema_id,
            policy_sha256='u', h_order=['h0', 'h1'], data_order=['toy'], reference_sha256='LB',
            solve_seed=501, u_interface='select-mix-v2', action_schema='job-operation-machine',
            objective='mean(-Cmax/LB)', normalization='legacy-minmax', tie_rule='job-machine',
            evaluator_sha256='certified-t30')
        values.update(changes)
        return make_binding(**values)

    def test_names_match_real_legacy_signatures(self):
        from fjsp_usage.research.candidates import U_ARGS
        from heuristic_design.problems.tsp.candidates import U_ARGS as TSP_ARGS
        self.assertEqual(FJSP_LEGACY.fields, U_ARGS)
        self.assertEqual(TSP_LEGACY.fields, TSP_ARGS)

    def test_explicit_legacy_packet_no_online_input_change(self):
        values = (0., .5, .4, .1, 0., 0., -1)
        packet = legacy_packet('fjsp', values, member_count=10)
        self.assertEqual(packet['values'], values)
        self.assertEqual(len(packet['fields']), 7)
        self.assertEqual(legacy_packet('tsp', (0., 0., .2, .1, -1), member_count=5)['phase'], 'construction')

    def test_missing_terminal_nonfinite_and_wrong_id_rejected(self):
        for values in [(0., .5, 0., 0., 0., 0.),
                       (1., .5, 0., 0., 0., 0., -1),
                       (0., 0., 0., 0., 0., 0., -1),
                       (0., .5, None, 0., 0., 0., -1),
                       (0., .5, float('nan'), 0., 0., 0., -1),
                       (0., .5, True, 0., 0., 0., -1),
                       (0., .5, 0., 0., 0., 0., 10)]:
            with self.assertRaises(ValueError):
                legacy_packet('fjsp', values, member_count=10)

    def test_draft_unknown_and_cross_problem_never_execute(self):
        for problem, schema in [('fjsp', COMMON_DRAFT.schema_id),
                                ('tsp', FJSP_LEGACY.schema_id), ('fjsp', 'v999'), ('fjsp', '')]:
            with self.assertRaises(ValueError):
                require_executable_schema(problem, schema)

    def test_cache_identity_binds_policy_member_order_and_science(self):
        first = self.binding()
        self.assertTrue(assert_same_binding(first, copy.deepcopy(first)))
        for changes in [dict(policy_sha256='new-u'), dict(h_order=['h1', 'h0']),
                        dict(data_order=['different']), dict(reference_sha256='other-LB'),
                        dict(solve_seed=7), dict(normalization='different'),
                        dict(evaluator_sha256='T15'), dict(tie_rule='other')]:
            with self.assertRaises(ValueError):
                assert_same_binding(first, self.binding(**changes))

    def test_old_cache_and_tampered_binding_never_auto_upgrade(self):
        first = self.binding()
        for changed in [{}, {'fitness': -2.}, copy.deepcopy(first)]:
            if 'payload' in changed:
                changed['payload']['objective'] = 'wrong'
            with self.assertRaises(ValueError):
                assert_same_binding(first, changed)

    def test_router_rejects_draft_before_problem_entry(self):
        import importlib.util
        from pathlib import Path
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('problem_router',
            Path(__file__).resolve().parents[1]/'experiments/manage.py')
        router = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(router)
        with patch('sys.argv', ['manage.py', '--problem', 'fjsp', '--state-schema', COMMON_DRAFT.schema_id]), \
                patch('runpy.run_path', side_effect=AssertionError('no problem/API/solver entry')) as entry, \
                patch('sys.stderr'):
            with self.assertRaises(SystemExit) as stopped:
                router.main()
            self.assertEqual(stopped.exception.code, 2)
            entry.assert_not_called()

if __name__ == '__main__':
    unittest.main()
