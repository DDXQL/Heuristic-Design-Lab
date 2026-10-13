"""Full export on handwritten loopback only; no Leaf, benchmark or holdout."""
import json
from pathlib import Path
import tempfile
import unittest

from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.usage_v2.config import UsageConfig
from fjsp_usage.usage_v2.fixtures import acceptance
from fjsp_usage.usage_v2.workflow import UsageWorkflow
from fjsp_usage.usage_v2.training_export import export_results

ROOT = Path(__file__).resolve().parents[1]


class ExportTests(unittest.TestCase):
    def test_loopback_actual_response_export_rates_pairing_costs_and_source_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'toy'
            evidence = acceptance(directory, ROOT)
            self.assertEqual(evidence['new_real_requests'], 0)
            config = UsageConfig.from_dict(json.loads((directory / 'config.synthetic.json').read_text()))
            ds = StagedDataset(directory / 'toy-data/manifest.json', project_root=directory / 'toy-data', mode='synthetic')
            flow = UsageWorkflow(directory, config=config, dataset=ds, project_root=ROOT)
            report = export_results(flow)
            self.assertEqual(report['status'], 'COMPLETED_TRAINING_ONLY')
            self.assertEqual(report['request_slots'], 26)
            self.assertEqual(report['actual_currency_charge'], None)
            self.assertEqual(report['observed_total_account_debit_raw_quota'], None)
            self.assertEqual(report['unsettled_debit_records'], 26)
            groups = {g['arm']: g for g in report['groups']}
            self.assertEqual(groups['INIT']['duplicate_count'], 1)
            self.assertEqual(groups['A']['complete_valid_new_candidates'], 8)
            self.assertEqual(groups['B']['complete_valid_new_candidates'], 9)
            self.assertEqual(len(report['paired_best_train_results']), 2)
            self.assertTrue(any(c['profile']['dual_member_steps'] > 0 for c in report['actual_generated_code'] if c['arm'] == 'B'))
            self.assertEqual(len(report['actual_generated_code']), sum(g['syntax_legal_responses'] for g in report['groups']))
            for code in report['actual_generated_code']:
                self.assertTrue((directory / code['source']).is_file())
            self.assertTrue((directory / 'results/All_instance_results.csv').is_file())
            self.assertEqual(ds.opened, [])  # Export never solves anything.


if __name__ == '__main__': unittest.main()
