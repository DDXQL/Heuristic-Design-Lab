import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research_real.assets import load_h
from fjsp_usage.research_real.fixtures import fixture_server
from test_integration_smoke import ROOT, setup, test_reviews


def sources(tmp, url):
    a, b = setup(Path(tmp)/'a',url), setup(Path(tmp)/'b',url)
    a.generate_h_sample(); b.generate_h_sample()
    return a,b,[(a.directory,'h/0'),(b.directory,'h/0')]


class SmokeReuseTests(unittest.TestCase):
    def test_import_rechecks_full_train_then_real_review_gate_and_one_u_no_double_billing(self):
        with fixture_server() as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            a,b,refs = sources(tmp,url)
            target = setup(Path(tmp)/'target',url,total_request_cap=1)
            with patch('fjsp_usage.research_real.integration_smoke.JsonCandidateTransport',side_effect=AssertionError('no provider on import')):
                status = target.import_h_samples(refs)
            self.assertEqual(status['stage'],'HUMAN_REVIEW_REQUIRED')
            self.assertEqual(status['budget']['confirmed_sends'],0)
            self.assertEqual(status['budget']['known_input_tokens'],0)
            self.assertEqual(len(traffic['requests']),2)
            asset = target.read('Smoke_h_candidates.json','Integration_smoke_h_candidates')
            for row in asset['rows']:
                self.assertTrue(row['training_result']['valid'])
                self.assertEqual(len(row['training_result']['instances']),2)
                self.assertNotEqual(row['receipt']['ledger_identity'],target.ledger.identity)
            blank = json.loads((target.directory/'H_review_template.json').read_text())
            self.assertTrue(all(not any(fields.values()) for fields in blank.values()))
            with self.assertRaises(ValueError): target.review_h(blank)
            with self.assertRaises(FileNotFoundError): target.generate_u()
            self.assertFalse((target.directory/'Smoke_H_reviewed.json').exists())
            with patch('fjsp_usage.research_real.staged_evaluation.evaluate',side_effect=AssertionError('no repeated evaluation')):
                target.import_h_samples(refs)
            # This explicit review is unit-test data, never real human evidence.
            target.review_h(test_reviews(target))
            status = target.generate_u()
            self.assertEqual(status['stage'],'INTEGRATION_ACCEPTANCE_COMPLETE')
            self.assertEqual(status['budget']['confirmed_sends'],1)
            self.assertEqual(len(traffic['requests']),3)
            with patch('fjsp_usage.research_real.staged_evaluation.evaluate',side_effect=AssertionError('no repeated evaluation')):
                target.generate_u()
            self.assertEqual(len(traffic['requests']),3)
            H = target.read('Smoke_H_reviewed.json','Integration_smoke_H_reviewed')
            with self.assertRaises(ValueError):
                load_h(H,mode='synthetic',context=target.context,size=2,names=target.dataset.names['train'])
            self.assertEqual({s for s,n in target.dataset.opened},{'train'})

    def test_old_timeout_is_preserved_and_response_is_freshly_evaluated(self):
        with fixture_server() as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            a,b,refs = sources(tmp,url)
            # Simulate only a past invalid evaluation, not a successful batch.
            cache_path = a.directory/'evaluations.json'
            cache = json.loads(cache_path.read_text())
            record = next(iter(cache['records'].values()))
            record['result'] = {'valid':False,'fitness':None,'total_instances':2,
                                'instances':[],'error_type':'Timeout','error':'past short deadline'}
            cache_path.write_text(json.dumps(cache))
            before = cache_path.read_bytes()
            target = setup(Path(tmp)/'target',url)
            target.import_h_samples(refs)
            self.assertEqual(cache_path.read_bytes(),before)
            self.assertEqual(len(traffic['requests']),2)
            self.assertTrue(all(row['training_result']['valid'] for row in
                target.read('Smoke_h_candidates.json','Integration_smoke_h_candidates')['rows']))

    def test_unconfirmed_source_wrong_mode_usage_or_duplicates_stop_without_provider(self):
        for corruption in ('unconfirmed','usage','mode','duplicate'):
            with self.subTest(corruption=corruption),fixture_server() as (url,traffic),tempfile.TemporaryDirectory() as tmp:
                a,b,refs = sources(tmp,url)
                if corruption == 'duplicate': refs=[refs[0],refs[0]]
                elif corruption == 'mode':
                    p=a.directory/'protocol.json';data=json.loads(p.read_text());data['mode']='real';p.write_text(json.dumps(data))
                else:
                    p=a.directory/'budget.json';data=json.loads(p.read_text());r=next(iter(data['records'].values()))
                    if corruption == 'unconfirmed': r['send_confirmed']=False
                    else:r['usage']['input_tokens']+=1
                    p.write_text(json.dumps(data))
                target=setup(Path(tmp)/'target',url)
                with patch('fjsp_usage.research_real.integration_smoke.JsonCandidateTransport',side_effect=AssertionError('no provider')):
                    with self.assertRaises(ValueError): target.import_h_samples(refs)
                self.assertEqual(target.ledger.summary()['confirmed_sends'],0)
                self.assertEqual(target.dataset.opened,[])
                self.assertFalse((target.directory/'Smoke_h_candidates.json').exists())

    def test_snapshot_tamper_rejected_before_U_and_changed_import_plan_rejected(self):
        with fixture_server() as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            a,b,refs=sources(tmp,url);target=setup(Path(tmp)/'target',url)
            target.import_h_samples(refs);target.review_h(test_reviews(target))
            with self.assertRaises(ValueError): target.import_h_samples(refs[::-1])
            p=target.directory/'imported_sources/0/h_requests.json';p.write_text(p.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'snapshot changed'): target.generate_u()
            self.assertEqual(len(traffic['requests']),2)


if __name__ == '__main__': unittest.main()
