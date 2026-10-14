"""Synthetic evidence only: migrated model cannot bypass common billing gates."""
from copy import deepcopy
from dataclasses import replace, asdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.usage_v2.model_migration import (MODEL, PROVIDER_MIGRATION_VERSION, RISK_POLICY,
    check_provider_migration, audit_common_evidence)
from fjsp_usage.usage_v2.registration import file_hash, peer_terminal_audit
from test_usage_v22_registration import save, settled_peer


def common_fixture(root):
    from fjsp_usage.usage_v2.model_migration import RISK_POLICY, EXPRESSION
    peer = settled_peer(root)
    p = json.loads((peer / 'protocol.json').read_text())
    provider = asdict(ProviderConfig(endpoint='https://leafapi.cc/v1/chat/completions',
        model=MODEL, protocol='openai-chat-v1', expected_response_model=MODEL,
        max_output_tokens=8192, input_token_reservation=65536, output_token_reservation=32768))
    p['config'].update(provider=provider, total_request_cap=61, platform_quota_ceiling=30000000,
        platform_quota_reservation=1000000, population_size=5, instance_timeout=15,
        initialization_cap=20, generations=1, attempts_per_generation=10, H_size=10,
        cross_parents=5, mutation_parents=1, review_timeout=3, training_diagnostics=True,
        conditional_research={'model_migration': {'risk_policy': RISK_POLICY, 'preflight_run': 'preflight'}})
    save(peer / 'protocol.json', p); context = digest(p)
    identity = digest({'config': p['config'], 'context': context})
    for name in ('budget.json', 'platform_quota.json'):
        b = json.loads((peer / name).read_text()); b['identity'] = identity; save(peer / name, b)
    g = json.loads((peer / 'Search_complete.json').read_text()); g.pop('artifact_sha256');g['context'] = context
    save(peer / 'Search_complete.json', seal(g))
    key = 'r201/diagnostic/access/000000'; usage = {'input_tokens': 2, 'output_tokens': 3}
    account = {'status': 'settled', 'send_confirmed': True, 'started_at': 100, 'finished_at': 110,
        'before_used': 50, 'after_used': 55, 'observed_account_delta': 5}
    invoice = {'model_name': MODEL, 'type': 2, 'quota': 5, 'request_id': 'supplier-id', 'created_at': 105}
    budget = json.loads((peer / 'budget.json').read_text())
    budget['records'][key] = {'phase': 'r201/diagnostic', 'status': 'completed', 'send_confirmed': True, 'usage': usage}
    save(peer / 'budget.json', budget)
    quota = json.loads((peer / 'platform_quota.json').read_text()); quota['records'][key] = account
    save(peer / 'platform_quota.json', quota)
    record = {'global_key': key, 'usage': usage, 'text': 'OK', 'status': 'completed',
        'response_metadata': {'model': MODEL, 'id': 'chat-id', 'gateway_request_id': 'supplier-id', 'billing_certified': True}}
    save(peer / 'Diagnostic_verified.json', seal({'kind': 'Diagnostic_verified', 'mode': 'real',
        'context': context, 'record': record, 'candidate': False}))
    save(peer / 'billing/proof.json', {'global_key': key, 'status': 'invoice_account_matched',
        'transport_status': 'completed', 'wire_usage': usage, 'original_quota_record': account,
        'before': {'success': True, 'records': []}, 'after': {'success': True, 'records': [invoice]},
        'invoice': invoice, 'actual_platform_units': 5})
    save(peer / 'Migration_final.json', seal({'kind': 'Migration_final', 'mode': 'real',
        'context': context, 'status': 'COMPLETED_TRAIN_ONLY'}))
    save(peer / 'Exclusive_call_handoff.json', {'caller_released': True, 'status': 'COMPLETED_TRAIN_ONLY',
        'budget_file_sha256': file_hash(peer / 'budget.json'), 'quota': quota})
    pre = root / 'runs/preflight'
    save(pre / 'pricing.json', {'success': True, 'inference_requests': 0,
        'models': [{'model_name': MODEL, 'enable_groups': ['codex-deafult'], 'billing_expr': EXPRESSION}],
        'group_ratio': {'codex-deafult': 0.5}})
    save(pre / 'status.json', {'public_fields': {'quota_per_unit': 500000}})
    save(pre / 'models.json', {'locked_model_listed': True})
    return peer, key


class MigrationTests(unittest.TestCase):
    def test_exact_approved_source_target_and_H_binding_required(self):
        old = ProviderConfig(endpoint='https://leafapi.cc/v1/chat/completions', model='gpt-5.6-sol',
            protocol='openai-chat-v1', expected_response_model='gpt-5.6-sol')
        new = replace(old, model=MODEL, expected_response_model=MODEL)
        migration = {'version': PROVIDER_MIGRATION_VERSION, 'confirmation_person': 'DDXQL',
            'source_provider': asdict(old), 'target_provider': asdict(new), 'source_H_sha256': 'H',
            'risk_policy': RISK_POLICY}
        config = SimpleNamespace(provider=new, provider_migration=migration, payload=lambda: {'provider': asdict(new)})
        check_provider_migration(config, asdict(old), 'H')
        for key, value in [('source_H_sha256', 'other'), ('confirmation_person', 'placeholder'),
                           ('source_provider', {**asdict(old), 'model': 'OTHER'})]:
            changed = deepcopy(migration); changed[key] = value; config.provider_migration = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_provider_migration(config, asdict(old), 'H')

    def test_new_model_filter_cannot_accept_old_stopped_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            settled_peer(Path(tmp))
            with self.assertRaisesRegex(BudgetStop, 'TERMINAL_BATCH'):
                peer_terminal_audit(tmp, model=MODEL)

    def test_successful_diagnostic_invoice_pricing_and_common_provider_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); peer, _ = common_fixture(root); result = audit_common_evidence(root)
            self.assertEqual(result['provider']['model'], MODEL)
            self.assertEqual(result['diagnostic_invoice']['quota'], 5)
            self.assertEqual(result['reservation'], 1000000)
            self.assertEqual(result['history_runs'], [peer.name])  # diagnostic counted once in the same ledger
            self.assertEqual(result['peer']['request_slots'], 2)

    def test_common_problem_is_never_bypassed_by_terminal_peer(self):
        for variant in ('diagnostic_failed', 'unknown_usage', 'account_halt', 'wrong_response_model',
                        'missing_receipt', 'wrong_debit', 'missing_pricing', 'unsupported_group',
                        'old_tariff', 'listing_missing', 'quota_unit', 'retry', 'missing_handoff'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); peer, key = common_fixture(root)
                b = json.loads((peer / 'budget.json').read_text())
                if variant == 'diagnostic_failed': b['records'][key]['status'] = 'failed'
                if variant == 'unknown_usage': b['records'][key]['usage'] = None
                if variant == 'retry': b['records']['r201/diagnostic/second'] = deepcopy(b['records'][key])
                save(peer / 'budget.json', b)
                handoff = json.loads((peer / 'Exclusive_call_handoff.json').read_text())
                handoff['budget_file_sha256'] = file_hash(peer / 'budget.json'); save(peer / 'Exclusive_call_handoff.json', handoff)
                if variant == 'account_halt':
                    path = peer / 'platform_quota.json'; b = json.loads(path.read_text()); b['halted'] = True; save(path, b)
                if variant == 'wrong_response_model':
                    path = peer / 'Diagnostic_verified.json'; b = json.loads(path.read_text()); b.pop('artifact_sha256')
                    b['record']['response_metadata']['model'] = 'gpt-5.6-sol'; save(path, seal(b))
                if variant in ('missing_receipt', 'wrong_debit'):
                    path = peer / 'billing/proof.json'; b = json.loads(path.read_text())
                    if variant == 'missing_receipt': b['after']['records'] = []
                    else: b['after']['records'][0]['quota'] = 9
                    save(path, b)
                pre = root / 'runs/preflight'
                if variant == 'missing_pricing': (pre / 'pricing.json').unlink()
                if variant in ('unsupported_group', 'old_tariff'):
                    path = pre / 'pricing.json'; b = json.loads(path.read_text())
                    if variant == 'unsupported_group': b['models'][0]['enable_groups'] = ['OTHER']
                    else: b['models'][0]['billing_expr'] = 'p*old'
                    save(path, b)
                if variant == 'listing_missing': save(pre / 'models.json', {'locked_model_listed': False})
                if variant == 'quota_unit': save(pre / 'status.json', {'public_fields': {'quota_per_unit': 1}})
                if variant == 'missing_handoff': (peer / 'Exclusive_call_handoff.json').unlink()
                with self.assertRaises((BudgetStop, ValueError)):
                    audit_common_evidence(root)

    def test_peer_writer_lock_blocks_even_after_successful_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); peer, _ = common_fixture(root)
            lock = peer / '.writer.lock'; lock.write_text('synthetic live owner')
            with self.assertRaisesRegex(BudgetStop, 'WRITER_LOCK'): audit_common_evidence(root)
            self.assertTrue(lock.exists())

    def test_prompt_risk_envelope_scales_and_does_not_clip_or_reprice_history(self):
        from fjsp_usage.usage_v2.model_migration import risk_reservation
        self.assertEqual(risk_reservation('OK')['points'], 410000)
        self.assertGreater(risk_reservation('x' * 200000)['points'], 410000)
        with self.assertRaisesRegex(BudgetStop, 'no clipping'): risk_reservation('x' * 400000)

    def test_dynamic_quota_record_preserves_two_old_holds_and_actual_next_risk(self):
        from fjsp_usage.usage_v2.model_migration import Gpt61UsageQuota
        with tempfile.TemporaryDirectory() as tmp:
            now = [0.0]; calls = []; used = iter((1500000, 1500010))
            def query():
                n = next(used)
                return {'quota': {'available': True, 'total_used': n, 'total_available': 100000000-n,
                    'total_granted': 100000000, 'unlimited_quota': False, 'expires_at': 0}}
            def dispatch(key, prompt, *, kind, on_sent):
                calls.append(key); on_sent()
                return {'text': 'fixture', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
            config = SimpleNamespace(conditional_research={'fixture': True}, development_acceptance=None,
                provider_migration={'risk_policy': RISK_POLICY}, seeds=(301,), platform_quota_ceiling=30000000,
                platform_quota_reservation=1000000, platform_quota_query_interval=75,
                payload=lambda: {'fixture': 'local-dynamic-quota-only'})
            wire = SimpleNamespace(config=config, identity='fixture', secret='unused-fixture',
                redact=lambda x:x, preflight=lambda p:None, dispatch=dispatch)
            guard = Gpt61UsageQuota(wire, Path(tmp)/'quota.json', 'fixture', query=query,
                retained_extra=24000000, tariff_query=lambda secret:{'fixture':True},
                clock=lambda:now[0], sleep=lambda n:now.__setitem__(0,now[0]+n))
            guard.dispatch('r301/A/CROSS/000000', 'short prompt')
            record = guard.data['records']['r301/A/CROSS/000000']
            self.assertEqual(record['reserved'], 410000)
            self.assertEqual(record['observed_account_delta'], 10)
            self.assertEqual(guard.check_retained(), 24000000)
            self.assertEqual(calls, ['r301/A/CROSS/000000'])

    def test_live_tariff_failure_stops_before_inference(self):
        from fjsp_usage.usage_v2.model_migration import Gpt61UsageQuota
        with tempfile.TemporaryDirectory() as tmp:
            config = SimpleNamespace(conditional_research={'fixture': True}, development_acceptance=None,
                platform_quota_ceiling=30000000, platform_quota_reservation=1000000,
                platform_quota_query_interval=75, payload=lambda: {'fixture':'tariff-stop'})
            wire = SimpleNamespace(config=config, identity='fixture', secret='unused-fixture',
                redact=lambda x:x, preflight=lambda p:self.fail('wire preflight reached'),
                dispatch=lambda *a,**k:self.fail('inference reached'))
            def failed(secret):raise BudgetStop('changed live tariff')
            guard = Gpt61UsageQuota(wire, Path(tmp)/'quota.json', 'fixture', tariff_query=failed)
            with self.assertRaisesRegex(BudgetStop,'changed live tariff'):guard.preflight('short')
            self.assertTrue(guard.data['halted'])

    def test_historical_invoice_matching_uses_original_model_after_migration(self):
        from test_usage_v22_billing import proof_fixture
        from test_conditional_research import setup
        from fjsp_usage.research_real.conditional_research import history_summary
        with tempfile.TemporaryDirectory() as tmp:
            flow, _, _ = setup(tmp); root = Path(tmp); prior = root / 'runs/prior'
            protocol = deepcopy(flow.protocol); identity = digest({'config': protocol['config'], 'context': digest(protocol)})
            account, proof, reconciliation = proof_fixture()
            proof['invoice']['model_name'] = flow.config.provider.model
            record = {'status': 'failed', 'send_confirmed': True, 'usage': None,
                      'reservation': {'input_tokens': 65536, 'output_tokens': 32768}}
            save(prior / 'protocol.json', protocol)
            save(prior / 'budget.json', {'identity': identity, 'records': {'request': record}})
            save(prior / 'platform_quota.json', {'identity': identity, 'observed_used': 10,
                'records': {'request': account}, 'invoice_reconciliations': [reconciliation]})
            save(prior / 'billing/proof.json', proof)
            declaration = deepcopy(flow.config.conditional_research); declaration['history_batches'].append('prior')
            declaration['source_files_sha256'].update({str(p.relative_to(root / 'runs')): file_hash(p)
                for p in prior.rglob('*') if p.is_file()})
            target = replace(flow.config, conditional_research=declaration,
                             provider=replace(flow.config.provider, model=MODEL))
            report = history_summary(root, target)
            self.assertEqual(report['historical_request_slots'], 7)
            self.assertEqual(report['retained_account_hold'], 12000000)
            row = next(r for r in report['unknown_requests'] if r['run'] == 'prior')
            self.assertEqual(row['account_hold'], 0)
            self.assertIsNone(row['wire_usage'])
            self.assertEqual(row['token_reservation'], record['reservation'])


if __name__ == '__main__': unittest.main()
