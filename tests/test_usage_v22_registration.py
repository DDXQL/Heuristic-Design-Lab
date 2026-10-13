"""Toy ledgers only: peer completion, settlement, alias counting and dispatch."""
from pathlib import Path
import json
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.usage_v2.registration import (peer_terminal_audit, inventory, SerialGuard,
    SerialTransport, VERSION, verify_source_group, file_hash)
from fjsp_usage.usage_v2.training_export import observed_profile


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def settled_peer(root):
    directory = root / 'runs/peer-authorized'
    protocol = {'config': {'real_requests_authorized': True, 'seeds': [201],
        'total_request_cap': 60, 'purpose': 'research', 'provider': {'model': 'TEST-MODEL'}}}
    context = digest(protocol)
    save(directory / 'protocol.json', protocol)
    identity = digest({'config': protocol['config'], 'context': context})
    save(directory / 'budget.json', {'identity': identity, 'mode': 'real', 'halted': False,
        'records': {'request': {'status': 'completed', 'usage': {'input_tokens': 2, 'output_tokens': 3}, 'send_confirmed': True}}})
    save(directory / 'platform_quota.json', {'identity': identity, 'halted': False, 'observed_used': 100,
        'records': {'request': {'status': 'settled', 'observed_account_delta': 5}}})
    save(directory / 'Search_complete.json', seal({'kind': 'Search_complete', 'mode': 'real', 'context': context,
        'entries': [{'seed': 201, 'arm': a, 'status': 'completed'} for a in ('B0', 'B1', 'B2', 'P')]}))
    return directory


class SerialRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'local'; self.peer = Path(self.tmp.name) / 'peer'
        self.directory = settled_peer(self.peer)

    def test_terminal_settled_peer_passes_and_keeps_actual_slots(self):
        result = peer_terminal_audit(self.peer)
        self.assertEqual(result['request_slots'], 1)
        self.assertEqual(result['observed_used'], 100)
        self.assertEqual(result['terminal'], {a: 'completed' for a in ('B0', 'B1', 'B2', 'P')})

    def test_no_writer_lock_does_not_imply_terminal(self):
        (self.directory / 'Search_complete.json').unlink()
        with self.assertRaisesRegex(BudgetStop, 'TERMINAL'):
            peer_terminal_audit(self.peer)

    def test_initialization_budget_stop_is_terminal_but_settlement_must_be_clear(self):
        protocol = json.loads((self.directory / 'protocol.json').read_text())
        (self.directory / 'Search_complete.json').unlink()
        save(self.directory / 'r201/Initialization_status.json', seal({
            'kind': 'Initialization_status', 'mode': 'real', 'context': digest(protocol),
            'status': 'initialization_budget_stopped'}))
        self.assertEqual(peer_terminal_audit(self.peer)['terminal'], {'INIT': 'initialization_budget_stopped'})
        quota = json.loads((self.directory / 'platform_quota.json').read_text())
        quota.update(halted=True, stop_reason='missing supplier invoice')
        save(self.directory / 'platform_quota.json', quota)
        with self.assertRaisesRegex(BudgetStop, 'missing supplier invoice'):
            peer_terminal_audit(self.peer)

    def test_pending_scope_or_multiple_authorized_batches_do_not_pass(self):
        settled_peer(self.peer / 'nested')
        protocol_path = self.directory / 'protocol.json'
        protocol = json.loads(protocol_path.read_text()); protocol['config']['real_requests_authorized'] = False
        save(protocol_path, protocol)
        with self.assertRaises(BudgetStop):
            peer_terminal_audit(self.peer)

    def test_live_peer_lock_is_never_removed(self):
        lock = self.directory / '.writer.lock'; lock.write_text('fixture live lock')
        with self.assertRaisesRegex(BudgetStop, 'WRITER_LOCK'):
            peer_terminal_audit(self.peer)
        self.assertTrue(lock.exists())

    def test_unknown_usage_pending_quota_or_halt_blocks(self):
        for variant in ('unknown_usage', 'pending_quota', 'halted_quota', 'halted_budget'):
            settled_peer(self.peer)
            budget = json.loads((self.directory / 'budget.json').read_text())
            quota = json.loads((self.directory / 'platform_quota.json').read_text())
            if variant == 'unknown_usage': budget['records']['request']['usage'] = None
            if variant == 'pending_quota': quota['records']['request']['status'] = 'pending'
            if variant == 'halted_quota': quota['halted'] = True
            if variant == 'halted_budget': budget['halted'] = True
            save(self.directory / 'budget.json', budget); save(self.directory / 'platform_quota.json', quota)
            with self.subTest(variant=variant), self.assertRaises(BudgetStop):
                peer_terminal_audit(self.peer)

    def test_copied_ledgers_deduplicate_for_integrity_not_counter_sum(self):
        budget = json.loads((self.directory / 'budget.json').read_text())
        save(self.root / 'runs/copied/budget.json', budget)
        self.assertEqual(len(inventory([self.root, self.peer])), 1)
        budget['records']['other'] = {'status': 'completed'}
        save(self.root / 'runs/copied/budget.json', budget)
        with self.assertRaisesRegex(BudgetStop, 'divergent'):
            inventory([self.root, self.peer])

    def test_source_group_requires_exact_original_and_copy(self):
        relative = 'peer-authorized/budget.json'
        source = self.peer / 'runs' / relative
        target = self.root / 'runs' / relative; target.parent.mkdir(parents=True); target.write_bytes(source.read_bytes())
        pins = {relative: file_hash(source)}
        verify_source_group(self.root, self.peer, pins)
        target.write_text('{}')
        with self.assertRaises(BudgetStop): verify_source_group(self.root, self.peer, pins)

    def test_changed_peer_stops_before_inner_transport(self):
        active = self.root / 'runs/current'; active.mkdir(parents=True)
        flow = SimpleNamespace(context='context', project_root=self.root, directory=active,
            assert_current=lambda: None, config=object(), ledger=SimpleNamespace(data={'records': {}}))
        peer = peer_terminal_audit(self.peer)
        binding = {'version': VERSION, 'context': 'context', 'source_groups': [], 'peer': peer,
            'inventory': inventory([self.root, self.peer]), 'historical_slots': 80}
        inner = SimpleNamespace(identity='fixture', preflight=lambda p: self.fail('provider reached'),
            dispatch=lambda *a, **k: self.fail('provider reached'), redact=lambda x: x)
        transport = SerialTransport(inner, SerialGuard(flow, binding))
        changed = json.loads((self.directory / 'platform_quota.json').read_text()); changed['observed_used'] += 1
        save(self.directory / 'platform_quota.json', changed)
        with self.assertRaisesRegex(BudgetStop, 'changed'): transport.preflight('prompt')
        with self.assertRaisesRegex(BudgetStop, 'changed'): transport.dispatch('key', 'prompt')

    def test_ancestral_and_new_counter_used_instead_of_all_snapshot_slots(self):
        active = self.root / 'runs/current'; active.mkdir(parents=True)
        flow = SimpleNamespace(context='context', project_root=self.root, directory=active,
            assert_current=lambda: None, config=object(), ledger=SimpleNamespace(data={'records': {'own': {}}}))
        binding = {'version': VERSION, 'context': 'context', 'source_groups': [], 'peer': peer_terminal_audit(self.peer),
            'inventory': inventory([self.root, self.peer]), 'historical_slots': 80}
        with patch('fjsp_usage.usage_v2.registration.worktree_roots', return_value=[self.root, self.peer]), \
                patch('fjsp_usage.usage_v2.registration.history_summary', return_value={'historical_request_slots': 80}):
            self.assertEqual(SerialGuard(flow, binding).check()['historical_request_slots'], 80)


class ObservedUsageTests(unittest.TestCase):
    def test_MIX_single_is_not_dual_and_score_variation_is_not_winner_variation(self):
        result = {'valid': True, 'instances': [{'usage_decisions': [
            [0, [2, 1, 0], [0], [1, 0, 0], 0], [0, [3, 2, 1], [0], [1, 0, 0], 0],
            [1, [1, 0, 0], [0], [1, 0, 0], 0]]}]}
        profile = observed_profile(result)
        self.assertTrue(profile['selection_scores_vary_on_train'])
        self.assertFalse(profile['selected_member_varies_on_train'])
        self.assertTrue(profile['MIX_observed_but_only_single_member'])
        self.assertEqual(profile['dual_member_steps'], 0)

    def test_dynamic_weights_support_and_failed_prefix_are_distinguished(self):
        result = {'valid': False, 'instances': [{'usage_decisions': [
            [1, [3, 2, 0], [0, 1], [.6, .4, 0], 0], [1, [2, 3, 0], [0, 1], [.4, .6, 0], 1],
            [1, [0, 3, 2], [1, 2], [0, .6, .4], 1]]}]}
        profile = observed_profile(result)
        self.assertTrue(profile['dual_support_varies_on_train'])
        self.assertTrue(profile['dual_weights_vary_on_train'])
        self.assertFalse(profile['complete_train_valid'])


if __name__ == '__main__': unittest.main()
