from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from fjsp_usage.research.candidates import H_ARGS, U_ARGS
from fjsp_usage.research_real.budget import BudgetLedger, BudgetJournal
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.research_real.deepseek_pilot import DeepSeekPilot, PilotConfig, load_local_key
from fjsp_usage.research_real.fixtures import fixture_server
from fjsp_usage.research_real.real_transport import JsonCandidateTransport

ROOT = Path(__file__).resolve().parents[1]


def response(payload, index):
    is_h = 'def priority(' in payload['messages'][0]['content']
    code = ('def priority(' + ', '.join(H_ARGS) + '):\n    return -earliest_finish + '
            + str(index/100) + ' * processing_time') if is_h else (
            'def select_heuristic(' + ', '.join(U_ARGS) + '):\n    return 0 if progress < '
            + str(index/100) + ' else 1')
    return {'id': 'local', 'model': 'deepseek-flash',
            'choices': [{'message': {'content': '{Local handwritten fixture.}\n```python\n'
                                    + code + '\n```'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50,
                      'prompt_cache_hit_tokens': 40, 'prompt_cache_miss_tokens': 60}}


def config(url):
    return replace(PilotConfig(), mode='synthetic', provider=replace(PilotConfig().provider,
                   endpoint=url, api_key_env=None))


class DeepSeekPilotTests(unittest.TestCase):
    def test_provider_wire_cache_usage_and_no_replay(self):
        with fixture_server(responder=response) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
            c = config(url)
            ledger = BudgetLedger(Path(tmp)/'budget.json', c, 'test')
            journal = BudgetJournal(Path(tmp)/'journal.json', phase='probe', cap=1,
                                    transport=JsonCandidateTransport(c), ledger=ledger)
            result = journal.request('one', 'def priority(')
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['usage'], {'input_tokens': 100, 'output_tokens': 50})
            self.assertEqual(result['response_metadata']['cached_tokens'], 40)
            sent = traffic['requests'][0]
            self.assertEqual(sent['thinking'], {'type': 'disabled'})
            self.assertEqual(sent['max_tokens'], 2048)
            self.assertNotIn('max_completion_tokens', sent)
            self.assertNotIn('request_id', sent)
            journal.request('one', 'def priority(')
            self.assertEqual(len(traffic['requests']), 1)

    def test_invalid_cache_detail_preserves_known_total_usage(self):
        for fault in ('bool', 'sum', 'disagree'):
            def bad(payload, index):
                value = response(payload, index)
                if fault == 'bool': value['usage']['prompt_cache_hit_tokens'] = True
                if fault == 'sum': value['usage']['prompt_cache_miss_tokens'] = 59
                if fault == 'disagree': value['usage']['prompt_tokens_details'] = {'cached_tokens': 39}
                return value
            with self.subTest(fault=fault), fixture_server(responder=bad) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
                c = config(url)
                ledger = BudgetLedger(Path(tmp)/'b.json', c, 'test')
                journal = BudgetJournal(Path(tmp)/'j.json', phase='probe', cap=1,
                                        transport=JsonCandidateTransport(c), ledger=ledger)
                result = journal.request('one', 'hello')
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['usage'], {'input_tokens':100, 'output_tokens':50})
                self.assertEqual(len(traffic['requests']), 1)

    def test_full_local_pilot_and_resume_without_additional_requests(self):
        with fixture_server(responder=response) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
            c = config(url)
            first = DeepSeekPilot(tmp, root=ROOT, config=c).run()
            self.assertEqual(first['search_phase'], 'completed')
            self.assertEqual(first['samples']['h_samples']['valid'], 6)
            self.assertEqual(len(first['population']), 3)
            self.assertEqual(len(traffic['requests']), 20)
            self.assertFalse(first['formal_experiment'])
            self.assertFalse(first['validation_test_evaluated'])
            self.assertEqual(len(first['inputs']), 1)
            second = DeepSeekPilot(tmp, root=ROOT, config=c).run()
            self.assertEqual(second['search_phase'], 'completed')
            self.assertEqual(len(traffic['requests']), 20)
            self.assertEqual(second['budget']['request_slots'], 20)
            for result in json.loads((Path(tmp)/'h_samples_results.json').read_text()):
                self.assertTrue(result['evaluation']['instances'][0]['feasible'])

    def test_unknown_usage_or_http_fault_stops_after_first_call_even_on_resume(self):
        for fault in ('unknown', 'http', 'overrun'):
            def bad(payload, index):
                value = response(payload,index)
                if fault == 'unknown': value.pop('usage')
                return value
            with self.subTest(fault=fault), fixture_server(responder=bad,
                    script=({'status':401},) if fault == 'http' else ()) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
                c = config(url)
                if fault == 'overrun':
                    c = replace(c, provider=replace(c.provider, input_token_reservation=99))
                result = DeepSeekPilot(tmp, root=ROOT, config=c).run()
                self.assertTrue(result['stop_reason'])
                self.assertEqual(len(traffic['requests']), 1)
                DeepSeekPilot(tmp, root=ROOT, config=c).run()
                self.assertEqual(len(traffic['requests']), 1)

    def test_config_lock_and_literal_secret_file(self):
        with self.assertRaises(ValueError):
            ProviderConfig('https://api.deepseek.com/chat/completions', 'deepseek-flash',
                           protocol='deepseek-chat-v1')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'.env.deepseek.local'
            path.write_text('DEEPSEEK_API_KEY=sk-local-fixture-only\n')
            self.assertEqual(load_local_key(path), 'sk-local-fixture-only')
            for text in ('DEEPSEEK_API_KEY=sk-****', 'DEEPSEEK_API_KEY=$(touch sentinel)',
                         'DEEPSEEK_API_KEY=sk-local-fixture-only\nOTHER=value'):
                path.write_text(text)
                with self.assertRaises(ValueError): load_local_key(path)
            self.assertFalse((Path(tmp)/'sentinel').exists())

    def test_budget_blocks_dispatch_and_resume_cannot_expand_cap(self):
        for cap in ('money', 'requests'):
            with self.subTest(cap=cap), fixture_server(responder=response) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
                c = config(url)
                c = replace(c, cost_cap_estimate=0.01) if cap == 'money' else replace(c, total_request_cap=8)
                result = DeepSeekPilot(tmp, root=ROOT, config=c).run()
                self.assertTrue(result['stop_reason'])
                self.assertEqual(len(traffic['requests']), 0 if cap == 'money' else 8)
                DeepSeekPilot(tmp, root=ROOT, config=c).run()
                self.assertEqual(len(traffic['requests']), 0 if cap == 'money' else 8)
                with self.assertRaises(ValueError):
                    DeepSeekPilot(tmp, root=ROOT, config=replace(c, total_request_cap=51))


if __name__ == '__main__':
    unittest.main()
