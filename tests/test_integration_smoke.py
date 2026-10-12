from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.assets import load_h, seal
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.research_real.fixtures import fixture_server, fixture_response
from fjsp_usage.research_real.integration_smoke import SmokeConfig, IntegrationSmoke
from fjsp_usage.research_real.staged_evaluation import StagedDataset, create_synthetic_dataset

ROOT = Path(__file__).resolve().parents[1]


def setup(tmp,endpoint,**changes):
    root = Path(tmp)
    manifest = create_synthetic_dataset(root/'fixtures',count=2)
    dataset = StagedDataset(manifest,project_root=manifest.parent,mode='synthetic')
    config = SmokeConfig(provider=ProviderConfig(endpoint,'LOCAL-TEST',total_timeout=3),
        mode='synthetic',price_verified=True,input_price_per_million=1,
        output_price_per_million=1,price_source='synthetic fixture, not supplier pricing')
    config = replace(config,**changes)
    return IntegrationSmoke(root/'smoke',config=config,dataset=dataset,project_root=ROOT)


def test_reviews(flow):
    # Explicit test data only. The runner never manufactures these approvals.
    return {row['candidate']['key']:{'description':'Test review: read exact fixture expression.',
        'reviewer':'unit test','method':'explicit-unit-test-review','note':'synthetic fixture; no human research evidence'}
        for row in flow.read('Smoke_h_candidates.json','Integration_smoke_h_candidates')['rows']}


class SmokeTests(unittest.TestCase):
    def test_one_h_receipt_full_train_resume_and_no_H_or_U_authorization(self):
        with fixture_server() as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            flow = setup(tmp,url,total_request_cap=1)
            result = flow.generate_h_sample()
            self.assertEqual(result['stage'],'SINGLE_H_ACCEPTANCE_COMPLETE')
            sample = flow.read('Smoke_h_sample.json','Integration_smoke_h_sample')
            self.assertTrue(sample['row']['training_result']['valid'])
            self.assertEqual(len(sample['row']['training_result']['instances']),2)
            with patch('fjsp_usage.research_real.staged_evaluation.evaluate',side_effect=AssertionError('no repeat')):
                flow.generate_h_sample()
            self.assertEqual(len(traffic['requests']),1)
            self.assertFalse((flow.directory/'Smoke_H_reviewed.json').exists())
            self.assertFalse((flow.directory/'Smoke_h_candidates.json').exists())
            self.assertFalse((flow.directory/'H_review_template.json').exists())
            with self.assertRaises(FileNotFoundError): flow.generate_u()
            self.assertEqual(len(traffic['requests']),1)
            self.assertEqual({split for split,name in flow.dataset.opened},{'train'})

    def test_explicit_unpriced_real_smoke_has_three_request_cap_and_unknown_cost(self):
        from fjsp_usage.research_real.budget import BudgetLedger
        config = SmokeConfig(real_requests_authorized=True, total_request_cap=3,
            cost_cap_estimate=None, unpriced_requests_authorized=True)
        with patch.dict('os.environ', {'LEAFAPI_API_KEY':'local-test-not-a-real-key'}):
            config.check_dispatch()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = BudgetLedger(Path(tmp)/'budget.json',config,'test-only')
            for key,phase in (('h0','smoke/h'),('h1','smoke/h'),('u0','smoke/u')):
                ledger.reserve(key,phase,key)
                ledger.confirm_send(key)
                ledger.settle(key,status='completed',usage={'input_tokens':100,'output_tokens':50},elapsed_seconds=1)
            with self.assertRaises(BudgetStop): ledger.reserve('extra','smoke/h','extra')
            summary = ledger.summary()
            self.assertEqual(summary['confirmed_sends'],3)
            self.assertEqual(summary['known_input_tokens'],300)
            self.assertIsNone(summary['known_usage_cost_estimate'])
            self.assertIsNone(summary['estimated_cost_stop'])
        with self.assertRaises(BudgetStop):
            replace(config,unpriced_requests_authorized=False,cost_cap_estimate=5).check_dispatch()

    def test_unpriced_authorization_cannot_remove_all_bounds_or_invent_prices(self):
        with self.assertRaises(ValueError): SmokeConfig(cost_cap_estimate=None)
        base = dict(total_request_cap=3,cost_cap_estimate=None,unpriced_requests_authorized=True)
        for changes in ({'total_request_cap':4},{'cost_cap_estimate':5},
                        {'unpriced_requests_authorized':1},{'mode':'synthetic'},
                        {'input_price_per_million':1,'output_price_per_million':1},
                        {'price_verified':True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                SmokeConfig(**(base|changes))

    def test_native_chat_wire_candidate_review_and_full_train_chain(self):
        def chat_reply(payload,index):
            prompt=payload['messages'][0]['content']
            kind='U' if 'def select_heuristic(' in prompt else 'h'
            fixture=fixture_response({'kind':kind},index)
            return {'id':'local-chat-test','model':'LOCAL-TEST',
                'choices':[{'message':{'content':fixture['text']},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':100,'completion_tokens':50,
                    'prompt_tokens_details':{'cached_tokens':40},
                    'completion_tokens_details':{'reasoning_tokens':20}}}
        with fixture_server(responder=chat_reply) as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            provider=ProviderConfig(url,'LOCAL-TEST',protocol='openai-chat-v1',temperature=None,
                expected_response_model='LOCAL-TEST')
            flow=setup(tmp,url,provider=provider)
            flow.generate_h(); flow.review_h(test_reviews(flow)); result=flow.generate_u()
            self.assertEqual(len(traffic['requests']),3)
            self.assertTrue(all('messages' in p and 'kind' not in p for p in traffic['requests']))
            self.assertEqual(result['budget']['known_input_tokens'],300)
            self.assertEqual(result['budget']['known_output_tokens'],150)
            journal=json.loads((flow.directory/'u_requests.json').read_text())
            metadata=journal['requests']['u/0']['response_metadata']
            self.assertEqual(metadata['model'],'LOCAL-TEST')
            self.assertEqual(metadata['cached_tokens'],40)
            self.assertEqual(metadata['reasoning_tokens'],20)
            self.assertEqual({s for s,n in flow.dataset.opened},{'train'})

    def test_generated_h_full_train_pending_review_then_u_no_holdouts_and_resume(self):
        with fixture_server() as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            flow = setup(tmp,url)
            result = flow.generate_h()
            self.assertEqual(result['stage'],'HUMAN_REVIEW_REQUIRED')
            self.assertEqual(len(traffic['requests']),2)
            template = json.loads((flow.directory/'H_review_template.json').read_text())
            self.assertTrue(all(not any(r.values()) for r in template.values()))
            source = flow.read('Smoke_h_candidates.json','Integration_smoke_h_candidates')
            self.assertTrue(all(len(r['training_result']['instances'])==2 for r in source['rows']))
            with self.assertRaises(FileNotFoundError): flow.generate_u()
            with self.assertRaises(ValueError): flow.review_h(template)
            self.assertEqual(len(traffic['requests']),2)
            self.assertFalse((flow.directory/'Smoke_H_reviewed.json').exists())
            template_path = flow.directory/'H_review_template.json'
            template_path.write_text(json.dumps(test_reviews(flow)))
            before = template_path.read_bytes()
            flow.generate_h()
            self.assertEqual(template_path.read_bytes(),before)
            flow.review_h(test_reviews(flow))
            result = flow.generate_u()
            self.assertEqual(result['stage'],'INTEGRATION_ACCEPTANCE_COMPLETE')
            self.assertEqual(len(traffic['requests']),3)
            self.assertEqual({s for s,n in flow.dataset.opened},{'train'})
            self.assertEqual(result['budget']['known_input_tokens'],3*64)
            self.assertEqual(result['budget']['known_output_tokens'],3*48)
            self.assertEqual(result['budget']['cost_currency'],'CNY')
            self.assertFalse((flow.directory/'H_frozen.json').exists())
            with (patch('fjsp_usage.research_real.integration_smoke.JsonCandidateTransport',side_effect=AssertionError('no dispatch')),
                  patch('fjsp_usage.research_real.staged_evaluation.evaluate',side_effect=AssertionError('no evaluation'))):
                flow.generate_h(); flow.review_h(test_reviews(flow)); flow.generate_u()
            self.assertEqual(len(traffic['requests']),3)
            H = flow.read('Smoke_H_reviewed.json','Integration_smoke_H_reviewed')
            with self.assertRaises(ValueError):
                load_h(H,mode='synthetic',context=flow.context,size=2,names=flow.dataset.names['train'])
            path=flow.dataset.paths['train'][0]
            path.write_bytes(path.read_bytes()+b'\n# altered train input\n')
            with self.assertRaisesRegex(ValueError,'hash mismatch'): flow.generate_h()

    def test_unknown_prices_stop_before_transport_or_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = setup(tmp,'http://127.0.0.1:1/test',price_verified=False,
                         input_price_per_million=None,output_price_per_million=None)
            with patch('fjsp_usage.research_real.integration_smoke.JsonCandidateTransport',side_effect=AssertionError('no provider')):
                with self.assertRaisesRegex(BudgetStop,'unverified'): flow.generate_h()
            self.assertEqual(flow.ledger.summary()['request_slots'],0)
            self.assertEqual(flow.dataset.opened,[])

    def test_missing_usage_or_http_failure_halts_after_one_send_no_retry(self):
        for fault in ({'missing_usage':True},{'status':503}):
            with self.subTest(fault=fault),fixture_server(script=(fault,)) as (url,traffic),tempfile.TemporaryDirectory() as tmp:
                flow = setup(tmp,url)
                with self.assertRaises(BudgetStop): flow.generate_h()
                with self.assertRaises(BudgetStop): flow.generate_h()
                self.assertEqual(len(traffic['requests']),1)
                self.assertTrue(flow.ledger.summary()['halted'])
                self.assertEqual(flow.ledger.summary()['unknown_usage_requests'],1)

    def test_duplicate_h_or_bad_candidate_stops_without_refill(self):
        for duplicate in (True,False):
            def responder(payload,index):
                row = fixture_response(payload,0 if duplicate else index)
                if not duplicate: row['text']='bad candidate'
                return row
            with fixture_server(responder=responder) as (url,traffic),tempfile.TemporaryDirectory() as tmp:
                flow=setup(tmp,url)
                with self.assertRaises(ValueError): flow.generate_h()
                with self.assertRaises(ValueError): flow.generate_h()
                self.assertEqual(len(traffic['requests']),2 if duplicate else 1)
                self.assertFalse((flow.directory/'Smoke_h_candidates.json').exists())

    def test_request_and_cny_reservations_stop_before_extra_send(self):
        for changes,expected in (({'total_request_cap':1},1),({'cost_cap_estimate':.00001},0)):
            with fixture_server() as (url,traffic),tempfile.TemporaryDirectory() as tmp:
                flow = setup(tmp,url,**changes)
                with self.assertRaises(BudgetStop): flow.generate_h()
                self.assertEqual(len(traffic['requests']),expected)

    def test_guard_configuration_source_changes_and_review_cannot_be_replaced(self):
        for changes in ({'total_request_cap':21},{'total_request_cap':True},
                        {'cost_cap_estimate':5.1},{'price_currency':'USD'},
                        {'price_verified':True},{'review_timeout':float('inf')}):
            with self.assertRaises(ValueError): SmokeConfig(**changes)
        with fixture_server() as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            flow=setup(tmp,url); flow.generate_h(); flow.review_h(test_reviews(flow))
            changed=test_reviews(flow)
            next(iter(changed.values()))['description']='Changed after review'
            with self.assertRaisesRegex(ValueError,'locked'): flow.review_h(changed)
            with self.assertRaises(ValueError):
                IntegrationSmoke(flow.directory,config=replace(flow.config,review_timeout=4),
                    dataset=flow.dataset,project_root=ROOT)


if __name__ == '__main__': unittest.main()
