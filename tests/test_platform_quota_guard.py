import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from fjsp_usage.research_real.budget import BudgetJournal, BudgetLedger, BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.quota_guard import QuotaGuardedTransport
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from fjsp_usage.research_real.fixtures import fixture_server


def quota(used):
    return {'quota': {'available': True, 'total_used': used, 'total_available': 1000-used,
        'total_granted': 1000, 'unlimited_quota': False, 'expires_at': 0}}


class FakeTransport:
    identity = 'local-only'
    redact = staticmethod(lambda value: value)
    def __init__(self):
        self.config = ExperimentConfig(ProviderConfig('https://leafapi.cc/v1/chat/completions',
            'gpt-5.6-sol', api_key_env='LEAFAPI_API_KEY'), mode='real', real_requests_authorized=True,
            platform_quota_ceiling=300, platform_quota_reservation=100)
        self.calls = 0
    def preflight(self, prompt):
        pass
    def dispatch(self, key, prompt, *, kind, on_sent):
        self.calls += 1
        on_sent()
        return {'text': 'candidate', 'usage': {'input_tokens': 5, 'output_tokens': 5}}


class QuotaTests(unittest.TestCase):
    def test_recent_balance_reused_and_actual_queries_paced(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [0.0]; ticks = []
            def sleep(seconds): now[0] += seconds
            def query():
                ticks.append(now[0])
                return quota(10 * len(ticks))
            t = FakeTransport()
            g = QuotaGuardedTransport(t, Path(tmp)/'q.json', 'ctx', query=query,
                clock=lambda: now[0], sleep=sleep)
            ledger = BudgetLedger(Path(tmp)/'b.json', t.config, 'ctx')
            j = BudgetJournal(Path(tmp)/'j.json', phase='H/init', cap=3, transport=g, ledger=ledger)
            self.assertEqual(j.request('one', 'first')['status'], 'completed')
            self.assertEqual(j.request('two', 'next')['status'], 'completed')
            # One initial GET, then one settlement GET per send; no duplicate preflight GET.
            self.assertEqual(ticks, [0.0, 75.0, 150.0])
            self.assertEqual(t.calls, 2)
            j.request('one', 'first')
            self.assertEqual(len(ticks), 3)
            restored = QuotaGuardedTransport(t, Path(tmp)/'q.json', 'ctx', query=query,
                clock=lambda: now[0], sleep=sleep)
            restored.preflight('new')
            self.assertEqual(len(ticks), 4)  # disk balance cannot authorize a new process unaudited

    def test_actual_settlement_restore_and_boundary_no_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = FakeTransport()
            values = iter((quota(190), quota(210)))
            guard = QuotaGuardedTransport(transport, Path(tmp)/'quota.json', 'ctx', clock=lambda: 0, sleep=lambda seconds: None, query=lambda: next(values))
            ledger = BudgetLedger(Path(tmp)/'budget.json', transport.config, 'ctx')
            journal = BudgetJournal(Path(tmp)/'journal.json', phase='H/init', cap=3, transport=guard, ledger=ledger)
            first = journal.request('one', 'prompt')
            self.assertEqual(first['status'], 'completed')
            self.assertEqual(guard.data['records']['H/init/one']['observed_account_delta'], 20)
            resumed = QuotaGuardedTransport(transport, Path(tmp)/'quota.json', 'ctx', clock=lambda: 0, sleep=lambda seconds: None, query=lambda: quota(210))
            journal = BudgetJournal(Path(tmp)/'journal.json', phase='H/init', cap=3, transport=resumed, ledger=ledger)
            self.assertEqual(journal.request('one', 'prompt'), first)
            with self.assertRaises(BudgetStop): journal.request('two', 'different')
            self.assertEqual(transport.calls, 1)
            self.assertEqual(ledger.summary()['request_slots'], 1)

    def test_unknown_query_pending_and_delayed_debit_block(self):
        for case in ('unavailable', 'pending', 'delayed'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                t = FakeTransport(); path = Path(tmp)/'quota.json'
                g = QuotaGuardedTransport(t, path, 'ctx', clock=lambda: 0, sleep=lambda seconds: None, query=lambda: quota(10))
                if case == 'unavailable': g.query = lambda: {'error': 'timeout'}
                if case == 'pending':
                    g.data['records']['old'] = {'status': 'pending'}; g.save()
                    g = QuotaGuardedTransport(t, path, 'ctx', clock=lambda: 0, sleep=lambda seconds: None, query=lambda: quota(10))
                if case == 'delayed':
                    g.dispatch('one', 'prompt')
                    self.assertEqual(t.calls, 1)
                with self.assertRaises(BudgetStop): g.preflight('next')
                self.assertEqual(t.calls, 1 if case == 'delayed' else 0)

    def test_post_query_failure_preserves_usage_and_blocks_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = FakeTransport(); values = iter((quota(10), {'error': 'offline'}))
            g = QuotaGuardedTransport(t, Path(tmp)/'q.json', 'ctx', clock=lambda: 0, sleep=lambda seconds: None, query=lambda: next(values))
            with self.assertRaises(BudgetStop) as caught: g.dispatch('one', 'prompt')
            self.assertEqual(caught.exception.usage, {'input_tokens': 5, 'output_tokens': 5})
            self.assertEqual(g.data['records']['one']['status'], 'settlement_unknown')
            with self.assertRaises(BudgetStop): g.preflight('next')
            self.assertEqual(t.calls, 1)

    def test_output_reservation_is_distinct_from_wire_limit(self):
        def response(payload, index):
            return {'model': 'locked', 'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}],
                    'usage': {'prompt_tokens': 5, 'completion_tokens': 4895}}
        with fixture_server(responder=response) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
            config = ExperimentConfig(ProviderConfig(url, 'locked', protocol='openai-chat-v1',
                max_output_tokens=4096, output_token_reservation=8192))
            ledger = BudgetLedger(Path(tmp)/'b.json', config, 'ctx')
            journal = BudgetJournal(Path(tmp)/'j.json', phase='H/init', cap=2,
                transport=JsonCandidateTransport(config), ledger=ledger)
            self.assertEqual(journal.request('one', 'hello')['status'], 'completed')
            self.assertFalse(ledger.data['halted'])
            self.assertEqual(traffic['requests'][0]['max_completion_tokens'], 4096)
            journal.request('two', 'new')
            self.assertEqual(len(traffic['requests']), 2)
            self.assertEqual(ledger.summary()['known_output_tokens'], 9790)

    def test_config_requires_consistent_explicit_guard(self):
        t = FakeTransport()
        for edits in ({'platform_quota_reservation': None}, {'platform_quota_ceiling': 99},
                      {'provider': replace(t.config.provider, endpoint='https://other.invalid/chat')}):
            with self.assertRaises(ValueError): replace(t.config, **edits)
        with self.assertRaises(ValueError): replace(t.config.provider, max_output_tokens=8192, output_token_reservation=4096)
