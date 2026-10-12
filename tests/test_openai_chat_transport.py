import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from fjsp_usage.research_real.config import ProviderConfig, ExperimentConfig
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from fjsp_usage.research_real.fixtures import fixture_server
from fjsp_usage.research_real.budget import BudgetLedger, BudgetJournal, BudgetStop


def response(payload, index):
    return {'id': 'local-only', 'model': 'locked-model', 'system_fingerprint': 'local',
            'choices': [{'message': {'content': '{local}\n```python\ndef x():\n return 1\n```'},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50,
                      'prompt_tokens_details': {'cached_tokens': 40},
                      'completion_tokens_details': {'reasoning_tokens': 20}}}


class ChatTests(unittest.TestCase):
    def test_provider_output_overrun_with_reasoning_halts_before_next_send(self):
        # Reproduce the observed Leaf totals without a paid request or key.
        def overrun(payload, index):
            reply = response(payload, index)
            reply['usage']['completion_tokens'] = 4895
            reply['usage']['completion_tokens_details']['reasoning_tokens'] = 4574
            return reply

        with fixture_server(responder=overrun) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
            c = ExperimentConfig(ProviderConfig(url, 'requested-alias', protocol='openai-chat-v1',
                max_output_tokens=4096, expected_response_model='locked-model'))
            ledger = BudgetLedger(Path(tmp)/'budget.json', c, 'local-overrun')
            journal = BudgetJournal(Path(tmp)/'journal.json', phase='H/init', cap=2,
                transport=JsonCandidateTransport(c), ledger=ledger)
            record = journal.request('one', 'hello', kind='h')
            self.assertEqual(traffic['requests'][0]['max_completion_tokens'], 4096)
            self.assertEqual(record['status'], 'completed')
            self.assertEqual(record['usage']['output_tokens'], 4895)
            self.assertEqual(record['response_metadata']['reasoning_tokens'], 4574)
            self.assertTrue(ledger.data['records'][record['global_key']]['reservation_overrun'])
            self.assertTrue(ledger.summary()['halted'])
            self.assertEqual(ledger.summary()['known_output_tokens'], 4895)
            restored = BudgetLedger(Path(tmp)/'budget.json', c, 'local-overrun')
            resumed = BudgetJournal(Path(tmp)/'journal.json', phase='H/init', cap=2,
                transport=JsonCandidateTransport(c), ledger=restored)
            self.assertEqual(resumed.request('one', 'hello', kind='h'), record)
            with self.assertRaises(BudgetStop):
                resumed.request('two', 'new candidate', kind='h')
            self.assertEqual(len(traffic['requests']), 1)
            self.assertEqual(restored.summary()['request_slots'], 1)

    def test_wire_usage_audit_and_restore(self):
        with fixture_server(responder=response) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
            c = ExperimentConfig(ProviderConfig(url, 'requested-alias', protocol='openai-chat-v1',
                  temperature=None, reasoning_effort='medium', expected_response_model='locked-model'))
            ledger = BudgetLedger(Path(tmp)/'budget.json', c, 'local')
            journal = BudgetJournal(Path(tmp)/'journal.json', phase='H/init', cap=2,
                                    transport=JsonCandidateTransport(c), ledger=ledger)
            record = journal.request('one', 'hello', kind='h')
            self.assertEqual(record['status'], 'completed')
            self.assertEqual(record['usage'], {'input_tokens':100, 'output_tokens':50})
            self.assertEqual(record['response_metadata']['cached_tokens'], 40)
            self.assertEqual(record['response_metadata']['reasoning_tokens'], 20)
            self.assertEqual(record['response_metadata']['model'], 'locked-model')
            payload = traffic['requests'][0]
            self.assertEqual(payload['messages'], [{'role':'user', 'content':'hello'}])
            self.assertEqual(payload['max_completion_tokens'], c.provider.max_output_tokens)
            self.assertNotIn('temperature', payload)
            self.assertNotIn('request_id', payload)
            self.assertEqual(payload['reasoning_effort'], 'medium')
            journal.request('one', 'hello', kind='h')
            self.assertEqual(len(traffic['requests']), 1)
            self.assertEqual(ledger.summary()['phases']['H/init']['reserved_or_settled_tokens'], 150)

    def test_faults_no_retry_and_known_usage_retained(self):
        for fault in ('length', 'model', 'missing', 'details', 'choices', 'refusal', 'http'):
            def responder(payload, index):
                r = response(payload,index)
                if fault == 'length': r['choices'][0]['finish_reason'] = 'length'
                if fault == 'model': r['model'] = 'other'
                if fault == 'missing': r.pop('usage')
                if fault == 'details': r['usage']['prompt_tokens_details']['cached_tokens'] = True
                if fault == 'choices': r['choices'] = []
                if fault == 'refusal': r['choices'][0]['message']['refusal'] = 'no'
                return r
            with self.subTest(fault=fault), fixture_server(responder=responder,
                    script=({'status':429},) if fault=='http' else ()) as (url, traffic), tempfile.TemporaryDirectory() as tmp:
                c = ExperimentConfig(ProviderConfig(url,'alias',protocol='openai-chat-v1',expected_response_model='locked-model'))
                ledger = BudgetLedger(Path(tmp)/'b.json',c,'local')
                journal = BudgetJournal(Path(tmp)/'j.json',phase='H/init',cap=1,transport=JsonCandidateTransport(c),ledger=ledger)
                r = journal.request('one','hello')
                self.assertEqual(r['status'],'completed' if fault=='missing' else 'failed')
                self.assertIsNone(r['usage']) if fault in ('missing','http') else self.assertEqual(r['usage']['output_tokens'],50)
                journal.request('one','hello')
                self.assertEqual(len(traffic['requests']),1)
