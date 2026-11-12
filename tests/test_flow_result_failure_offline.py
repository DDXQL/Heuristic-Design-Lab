"""Error receipt replay only: no worker, constructor, model or network."""
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch
from heuristic_design.core import flow_check as f
from heuristic_design.core.flow_check import evaluation_failure_layer
from heuristic_design.core.storage import write


class ResultFailureTests(unittest.TestCase):
    def test_actual_host_error_is_not_candidate_runtime(self):
        self.assertEqual(evaluation_failure_layer({
            'error_type': 'TypeError',
            'error': "StateAResult.__init__() got multiple values for argument 'member_sequence'",
        }), 'local_result_contract')

    def test_unrelated_candidate_error_keeps_its_category(self):
        self.assertEqual(evaluation_failure_layer({'error_type': 'TypeError', 'error': 'invalid candidate operand'}), 'candidate_runtime')
        self.assertEqual(evaluation_failure_layer({'error_type': 'ValueError', 'error': 'invalid action'}), 'candidate_runtime')

    def test_timeout_and_valid_receipt_remain_distinct(self):
        self.assertEqual(evaluation_failure_layer({'error_type': 'Timeout', 'error': 'deadline'}), 'evaluation_deadline')
        self.assertIsNone(evaluation_failure_layer(None))

    def test_frozen_predecessor_keeps_two_passes_charged(self):
        proof=f.predecessor_proof()
        self.assertEqual(proof['carried_solve_passes'],2)
        self.assertEqual(proof['API_reserved'],0)

    def test_original_prefix_is_read_only_and_new_API_material_blocks(self):
        proof=f.predecessor_proof()
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            shutil.copytree(f.ROOT/'deploy/flow-check/predecessor',base/'old')
            old=base/'old';(old/'.execution.lock').write_text('retained fixture lock')
            proof={**proof,'previous_directory':str(old)}
            with patch.object(f,'predecessor_proof',return_value=proof):
                f.verify_predecessor_live()
                write(old/'API_attempts.json',{'unexpected':'material'})
                with self.assertRaises(ValueError):f.verify_predecessor_live()
            self.assertEqual((old/'.execution.lock').read_text(),'retained fixture lock')

    def test_cluster_cannot_claim_a_third_evaluation_or_run_worker(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(f.lifecycle,'collect',side_effect=AssertionError('NO SOLVER')):
            with self.assertRaises(ValueError):
                f.evaluate(Path(tmp),{'evaluations':{'one':{},'two':{}}},{'site':'cluster'},type('Candidate',(),{'key':'three'})())


if __name__ == '__main__':
    unittest.main()
