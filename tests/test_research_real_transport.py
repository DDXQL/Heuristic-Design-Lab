import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fjsp_usage.research.protocol import digest
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.budget import BudgetLedger, BudgetJournal, BudgetStop, validate_usage
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.fixtures import fixture_server
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, TransportError
from fjsp_usage.research_real.evaluation_cache import EvaluationCache
from fjsp_usage.research_real.locking import RunLock


def config(endpoint, **changes):
    return ExperimentConfig(provider=ProviderConfig(endpoint, 'HANDWRITTEN-TEST', total_timeout=2),
        H_size=2, H_initialization_cap=3, population_size=3, cross_parents=2,
        attempts_per_generation=10, generations=1, initialization_cap=3, seeds=(1,2),
        total_request_cap=100, **changes)


class RealTransportTests(unittest.TestCase):
    def test_independent_parameters_and_invalid_configuration(self):
        value = ExperimentConfig(ProviderConfig('http://127.0.0.1:1/c', 'fixture'), H_size=7,
                                 population_size=10, cross_parents=5, mutation_parents=1)
        self.assertEqual((value.h_search().population_size, value.u_search(1).population_size,
                          value.u_search(1).cross_parents, value.mutation_parents), (7,10,5,1))
        for changes in ({'seeds': (1,1)}, {'H_size': True}, {'cross_parents': 11},
                        {'mutation_parents': 2}, {'total_token_cap': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ExperimentConfig(value.provider, **changes)
        with self.assertRaises(ValueError):
            config('https://example.invalid/c')
        with self.assertRaises(ValueError):
            ProviderConfig('http://example.invalid/c', 'model')
        with self.assertRaises(ValueError):
            ProviderConfig('https://secret:password@example.invalid/c', 'model')

    def test_http_faults_each_send_once_and_missing_usage_is_unknown(self):
        faults = ({'status':401}, {'status':429}, {'status':503}, {'malformed':True},
                  {'truncated':True}, {'missing_usage':True}, {})
        with fixture_server(script=faults) as (endpoint, traffic), tempfile.TemporaryDirectory() as tmp:
            c = config(endpoint)
            transport = JsonCandidateTransport(c)
            ledger = BudgetLedger(Path(tmp)/'ledger.json', c, 'context')
            journal = BudgetJournal(Path(tmp)/'journal.json', phase='r1/B0', cap=10, transport=transport, ledger=ledger)
            for i in range(len(faults)):
                record = journal.request(str(i), 'prompt'+str(i))
                self.assertEqual(record['status'], 'failed' if i < 5 else 'completed')
                self.assertEqual(journal.request(str(i), 'prompt'+str(i)), record)
            self.assertEqual(len(traffic['requests']), 7)
            self.assertEqual(ledger.summary()['confirmed_sends'], 7)
            self.assertIsNone(journal.data['requests']['5']['usage'])
            self.assertEqual(journal.data['requests']['6']['usage']['input_tokens'], 64)
            self.assertIsNone(ledger.summary()['phases']['r1/B0']['cost_estimate'])
            restored = BudgetJournal(Path(tmp)/'journal.json', phase='r1/B0', cap=10, transport=transport, ledger=ledger)
            restored.request('6', 'prompt6')
            self.assertEqual(len(traffic['requests']), 7)

    def test_read_timeout_and_slow_drip_total_deadline(self):
        from dataclasses import replace
        for fault, read in (({'delay':.7}, .1), ({'drip':.02}, .15)):
            with self.subTest(fault=fault), fixture_server(script=(fault,)) as (endpoint, traffic):
                c = config(endpoint)
                c = replace(c, provider=replace(c.provider, read_timeout=read, total_timeout=.45))
                started = time.monotonic()
                with self.assertRaises(TransportError):
                    JsonCandidateTransport(c).dispatch('one', 'prompt')
                self.assertLess(time.monotonic()-started, 2)
                self.assertEqual(len(traffic['requests']), 1)

    def test_global_and_phase_caps_stop_before_an_extra_http_send(self):
        from dataclasses import replace
        for limited in ('global', 'phase'):
            with self.subTest(limit=limited), fixture_server() as (endpoint, traffic), tempfile.TemporaryDirectory() as tmp:
                c = config(endpoint)
                if limited == 'global':
                    c = replace(c, total_request_cap=1)
                else:
                    caps = c.default_phase_caps()
                    caps.update({p:1 for p in caps if not p.endswith('/init') and not p.startswith('H/')})
                    c = replace(c, phase_request_caps=caps)
                ledger = BudgetLedger(Path(tmp)/'ledger.json', c, 'context')
                journal = BudgetJournal(Path(tmp)/'journal.json', phase='r1/B0', cap=10,
                                        transport=JsonCandidateTransport(c), ledger=ledger)
                journal.request('one', 'prompt')
                with self.assertRaises(BudgetStop):
                    journal.request('two', 'prompt')
                self.assertEqual(len(traffic['requests']), 1)
                self.assertEqual(ledger.summary()['request_slots'], 1)

    def test_real_auth_gate_and_secret_redaction(self):
        from dataclasses import replace
        def responder(payload, index):
            return {'text': 'credential-TEST-only', 'usage': None}
        with fixture_server(responder=responder) as (endpoint, traffic), tempfile.TemporaryDirectory() as tmp:
            c = replace(config(endpoint), mode='real', provider=ProviderConfig(endpoint, 'fixture', api_key_env='FJSP_TEST_SECRET'))
            with self.assertRaises(ValueError):
                JsonCandidateTransport(c)
            with patch.dict(os.environ, {'FJSP_TEST_SECRET':'credential-TEST-only'}):
                c = replace(c, real_requests_authorized=True)
                transport = JsonCandidateTransport(c)
                ledger = BudgetLedger(Path(tmp)/'ledger.json', c, 'context')
                journal = BudgetJournal(Path(tmp)/'journal.json', phase='r1/B0', cap=10, transport=transport, ledger=ledger)
                self.assertEqual(journal.request('one', 'safe prompt')['text'], '[REDACTED]')
            self.assertNotIn('credential-TEST-only', (Path(tmp)/'journal.json').read_text())
            self.assertNotIn('credential-TEST-only', (Path(tmp)/'ledger.json').read_text())
            self.assertNotIn('credential-TEST-only', json.dumps(traffic['requests']))

    def test_request_token_cost_caps_and_usage_overrun(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as tmp:
            c = replace(config('http://127.0.0.1:1/c'), total_request_cap=1)
            ledger = BudgetLedger(Path(tmp)/'requests.json', c, 'context')
            ledger.reserve('a', 'r1/B0', 'p')
            with self.assertRaises(BudgetStop):
                ledger.reserve('b', 'r1/B1', 'p')
            token = replace(c, total_token_cap=10)
            with self.assertRaises(BudgetStop):
                BudgetLedger(Path(tmp)/'tokens.json', token, 'context').reserve('a', 'r1/B0', 'p')
            cost = replace(c, cost_cap_estimate=.01, input_price_per_million=100,
                           output_price_per_million=100, price_source='fixture estimate')
            with self.assertRaises(BudgetStop):
                BudgetLedger(Path(tmp)/'cost.json', cost, 'context').reserve('a', 'r1/B0', 'p')
            ledger.settle('a', status='completed', usage={'input_tokens':70000, 'output_tokens':1}, elapsed_seconds=.1)
            self.assertTrue(ledger.summary()['halted'])
            self.assertIn('not certified', ledger.summary()['token_limit_basis'])
            with self.assertRaises(ValueError):
                validate_usage({'input_tokens': True, 'output_tokens':1})

    def test_uncertain_dispatch_is_not_replayed_and_known_usage_survives(self):
        class NoSend:
            identity = 'fixture'
            def preflight(self, prompt): pass
            def dispatch(self, *args, **kwargs): raise AssertionError('must not dispatch')
        with tempfile.TemporaryDirectory() as tmp:
            c = config('http://127.0.0.1:1/c')
            ledger = BudgetLedger(Path(tmp)/'ledger.json', c, 'context')
            transport = NoSend()
            journal = BudgetJournal(Path(tmp)/'journal.json', phase='r1/B0', cap=10, transport=transport, ledger=ledger)
            pkey = digest({'prompt':'p', 'kind':'U'})
            ledger.reserve('r1/B0/orphan', 'r1/B0', pkey)
            ledger.confirm_send('r1/B0/orphan')
            usage = {'input_tokens':12, 'output_tokens':4}
            ledger.settle('r1/B0/orphan', status='completed', usage=usage, elapsed_seconds=.2)
            result = journal.request('orphan', 'p')
            self.assertEqual(result['status'], 'interrupted')
            self.assertEqual(ledger.data['records']['r1/B0/orphan']['usage'], usage)
            ledger.reserve('r1/B0/pending', 'r1/B0', pkey)
            journal.data['requests']['pending'] = {'status':'pending', 'prompt_key':pkey, 'global_key':'r1/B0/pending'}
            atomic_json(journal.path, journal.data)
            self.assertEqual(journal.request('pending', 'p')['status'], 'interrupted')
            self.assertEqual(ledger.summary()['request_slots'], 2)

    def test_evaluation_resume_and_single_writer_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'cache.json'
            cache = EvaluationCache(path, 'context')
            good = {'valid':True, 'total_instances':1, 'fitness':-1.,
                    'instances':[{'file':'x', 'makespan':2, 'lower_bound':2., 'score':-1.}]}
            counter = []
            self.assertEqual(cache.get('good', ('x',), lambda: (counter.append(1) or good)), good)
            cache.get('good', ('x',), lambda: self.fail('repeat'))
            self.assertEqual(counter, [1])
            cache.data['records']['pending'] = {'status':'pending'}
            atomic_json(path, cache.data)
            interrupted = EvaluationCache(path, 'context').get('pending', ('x',), lambda: self.fail('repeat'))
            self.assertFalse(interrupted['valid'])
            self.assertIsNone(interrupted['fitness'])
            with self.assertRaises(ValueError):
                EvaluationCache(path, 'new-context')
            with RunLock(tmp):
                with self.assertRaises(RuntimeError):
                    with RunLock(tmp): pass
            self.assertFalse((Path(tmp)/'.writer.lock').exists())


if __name__ == '__main__':
    unittest.main()
