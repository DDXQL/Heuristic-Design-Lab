"""Pinned invoice proof; unknown response tokens are never changed to zero."""
import unittest
from copy import deepcopy
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.usage_v2.billing import match_invoice, certified_reconciliation


def proof_fixture():
    account = {'status': 'settled', 'started_at': 100, 'finished_at': 105,
        'before_used': 10, 'after_used': 10, 'observed_account_delta': 0, 'send_confirmed': True}
    invoice = {'request_id': 'new-id', 'created_at': 103, 'type': 5, 'model_name': 'TEST', 'quota': 0}
    before = {'success': True, 'records': []}; after = {'success': True, 'records': [invoice]}
    proof = {'global_key': 'request', 'status': 'invoice_account_matched', 'wire_usage': None,
        'transport_status': 'failed', 'original_quota_record': account,
        'before': before, 'after': after, 'invoice': invoice}
    reconciliation = {'global_key': 'request', 'proof_file': 'proof.json',
        'original_quota_record': account, 'invoice': invoice, 'wire_usage_still_unknown': True}
    return account, proof, reconciliation


class InvoiceTests(unittest.TestCase):
    def test_unique_failed_zero_charge_receipt_can_settle_account_not_wire_tokens(self):
        account, proof, reconciliation = proof_fixture()
        invoice = certified_reconciliation('request', account, [reconciliation],
            {'peer/billing/proof.json': proof}, 'peer', 'TEST')
        self.assertEqual(invoice['quota'], 0)
        self.assertIsNone(proof['wire_usage'])
        self.assertTrue(reconciliation['wire_usage_still_unknown'])

    def test_no_receipt_or_ambiguous_receipt_blocks(self):
        account, proof, _ = proof_fixture()
        for rows in ([], [proof['invoice'], {**proof['invoice'], 'request_id': 'second'}]):
            with self.assertRaises(BudgetStop):
                match_invoice(proof['before'], {'success': True, 'records': rows}, account, 'TEST', failed=True)

    def test_old_receipt_wrong_model_window_or_debit_cannot_settle(self):
        account, proof, _ = proof_fixture()
        for change in ({'model_name': 'OTHER'}, {'created_at': 50}, {'quota': 1}):
            after = {'success': True, 'records': [{**proof['invoice'], **change}]}
            with self.assertRaises(BudgetStop):
                match_invoice(proof['before'], after, account, 'TEST', failed=True)
        with self.assertRaises(BudgetStop):
            match_invoice(proof['after'], proof['after'], account, 'TEST', failed=True)

    def test_proof_or_original_record_tampering_is_rejected(self):
        account, proof, reconciliation = proof_fixture()
        altered = deepcopy(proof); altered['invoice']['quota'] = 1
        with self.assertRaises((ValueError, BudgetStop)):
            certified_reconciliation('request', account, [reconciliation],
                {'peer/billing/proof.json': altered}, 'peer', 'TEST')
        with self.assertRaises(ValueError):
            certified_reconciliation('request', {**account, 'after_used': 11}, [reconciliation],
                {'peer/billing/proof.json': proof}, 'peer', 'TEST')
        with self.assertRaises(ValueError):
            certified_reconciliation('request', account, [reconciliation], {}, 'peer', 'TEST')

    def test_prior_failed_invoice_keeps_unknown_token_reservation_in_cumulative_history(self):
        from dataclasses import replace
        import hashlib
        from pathlib import Path
        import tempfile
        from test_conditional_research import setup
        from fjsp_usage.research.events import atomic_json
        from fjsp_usage.research.protocol import digest
        from fjsp_usage.research_real.conditional_research import history_summary
        with tempfile.TemporaryDirectory() as temporary:
            flow, _, _ = setup(temporary)
            root = Path(temporary); prior = root / 'runs/prior'
            protocol = deepcopy(flow.protocol); context = digest(protocol)
            identity = digest({'config': protocol['config'], 'context': context})
            account, proof, reconciliation = proof_fixture()
            proof['invoice']['model_name'] = flow.config.provider.model
            key = 'request'
            record = {'status': 'failed', 'send_confirmed': True, 'usage': None,
                'reservation': {'input_tokens': 65536, 'output_tokens': 32768}}
            atomic_json(prior / 'protocol.json', protocol)
            atomic_json(prior / 'budget.json', {'identity': identity, 'records': {key: record}})
            atomic_json(prior / 'platform_quota.json', {'identity': identity, 'observed_used': 10,
                'records': {key: account}, 'invoice_reconciliations': [reconciliation]})
            atomic_json(prior / 'billing/proof.json', proof)
            declaration = deepcopy(flow.config.conditional_research)
            declaration['history_batches'].append('prior')
            declaration['source_files_sha256'].update({str(p.relative_to(root / 'runs')):
                hashlib.sha256(p.read_bytes()).hexdigest() for p in prior.rglob('*') if p.is_file()})
            config = replace(flow.config, conditional_research=declaration)
            history = history_summary(root, config)
            self.assertEqual(history['historical_request_slots'], 7)
            self.assertEqual(history['retained_account_hold'], 12000000)
            newest = next(r for r in history['unknown_requests'] if r['run'] == 'prior')
            self.assertEqual(newest['account_hold'], 0)
            self.assertIsNone(newest['wire_usage'])
            self.assertEqual(newest['token_reservation'], record['reservation'])
            self.assertEqual(newest['raw_record'], record)


if __name__ == '__main__': unittest.main()
