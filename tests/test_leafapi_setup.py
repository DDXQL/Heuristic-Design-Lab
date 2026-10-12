from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.leafapi import (load_local_key, provider, pilot_config,
    query_status, normalize_quota, MODEL)
from fjsp_usage.research_real.preparation import write_preparation
from fjsp_usage.research_real.staged_evaluation import StagedDataset, create_synthetic_dataset

ROOT = Path(__file__).resolve().parents[1]
QUOTA = {'code':True, 'data':{'total_granted':100,'total_used':30,'total_available':70,
    'unlimited_quota':False,'model_limits_enabled':True,'model_limits':{MODEL:True},'expires_at':0}}


@contextmanager
def metadata_server(statuses=(200,200)):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            requests.append((self.command,self.path,self.headers.get('Authorization')))
            body = QUOTA if self.path.rstrip('/') == '/api/usage/token' else {'data':[{'id':MODEL}]}
            raw = json.dumps(body).encode()
            self.send_response(statuses[len(requests)-1])
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Location','https://example.invalid/not-followed')
            self.end_headers(); self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        yield 'http://127.0.0.1:'+str(server.server_port), requests
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=1)


class LeafSetupTests(unittest.TestCase):
    def test_new_profile_keeps_historical_draft_and_updates_only_audit_and_deadline(self):
        c = ExperimentConfig.from_dict(json.loads((ROOT/'experiments/tier2/research_real_v1/config.api-pilot.draft.json').read_text()))
        current = pilot_config()
        self.assertEqual(c.instance_timeout,3)
        self.assertIsNone(c.provider.expected_response_model)
        self.assertEqual(current.instance_timeout,15)
        self.assertEqual(current.provider.expected_response_model,MODEL)
        old = c.payload(); old['instance_timeout'] = 15
        old['provider']['expected_response_model'] = MODEL
        self.assertEqual(old,current.payload())
        self.assertFalse(current.real_requests_authorized)
        self.assertEqual(c.provider.api_key_env,'LEAFAPI_API_KEY')
        self.assertEqual(c.provider.model,MODEL)
        self.assertEqual(c.total_request_cap,sum(c.phase_caps().values()))
        with self.assertRaises(ValueError): c.check_dispatch()

    def test_literal_key_file_and_placeholder_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'.env.leafapi.local'
            p.write_text('LEAFAPI_API_KEY="sk-fixture-local-only-123456"\n')
            self.assertEqual(load_local_key(p),'sk-fixture-local-only-123456')
            for content in ('LEAFAPI_API_KEY=sk-','LEAFAPI_API_KEY=sk-****',
                            'LEAFAPI_API_KEY=$(touch sentinel)', 'OTHER=sk-fixture-local-only-123456'):
                p.write_text(content)
                with self.assertRaises(ValueError): load_local_key(p)
            self.assertFalse((Path(tmp)/'sentinel').exists())

    def test_status_gets_only_metadata_without_model_inference(self):
        with metadata_server() as (url,requests):
            result=query_status('sk-fixture-local-only-123456',base_url=url)
        self.assertTrue(result['requested_model_listed'])
        self.assertTrue(result['quota']['allowed_by_explicit_token_limit'])
        self.assertEqual(result['quota']['total_available'],70)
        self.assertIn('NOT automatically CNY',result['quota']['unit'])
        self.assertEqual(result['inference_requests'],0)
        self.assertEqual([r[:2] for r in requests],[('GET','/api/usage/token'),('GET','/v1/models')])
        self.assertTrue(all(r[2]=='Bearer sk-fixture-local-only-123456' for r in requests))
        self.assertNotIn('sk-fixture-local-only-123456',json.dumps(result))

    def test_unauthorized_and_redirect_do_not_retry_or_follow(self):
        with metadata_server((401,302)) as (url,requests):
            result=query_status('sk-fixture-local-only-123456',base_url=url)
        self.assertEqual(len(requests),2)
        self.assertEqual(result['quota']['http_status'],401)
        self.assertEqual(result['models']['http_status'],302)
        self.assertIsNone(result['requested_model_listed'])

    def test_budget_query_omits_model_list(self):
        with metadata_server((200,)) as (url, requests):
            result = query_status('sk-fixture-local-only-123456', base_url=url, include_models=False)
        self.assertTrue(result['quota']['available'])
        self.assertEqual([r[:2] for r in requests], [('GET', '/api/usage/token')])
        self.assertNotIn('models', result)
        self.assertEqual(result['inference_requests'], 0)

    def test_explicit_canonical_path_and_secret_stays_in_header(self):
        with metadata_server() as (url,requests):
            result=query_status('sk-fixture-local-only-123456',base_url=url,quota_path='/api/usage/token/')
        self.assertTrue(result['quota']['available'])
        self.assertEqual(requests[0][1],'/api/usage/token/')
        self.assertEqual(len(requests),2)
        with self.assertRaises(ValueError):
            query_status('local-fixture',base_url=url,quota_path='/somewhere-else')

    def test_quota_validation_and_origin_validation(self):
        for value in (True,-1,float('inf')):
            body=json.loads(json.dumps(QUOTA)); body['data']['total_available']=value
            with self.assertRaises(ValueError): normalize_quota(body)
        for url in ('https://leafapi.cc?key=bad','https://user:password@leafapi.cc',
                    'http://example.invalid','https://leafapi.cc/path'):
            with self.assertRaises(ValueError): query_status('local-fixture',base_url=url)

    def test_offline_preparation_can_select_leaf_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=create_synthetic_dataset(Path(tmp)/'fixtures',count=1)
            dataset=StagedDataset(manifest,project_root=manifest.parent,mode='synthetic')
            write_preparation(Path(tmp)/'prepared',root=ROOT,dataset=dataset,provider=provider())
            c=ExperimentConfig.from_dict(json.loads((Path(tmp)/'prepared/config.formal.draft.json').read_text()))
            self.assertEqual(c.provider.model,MODEL)
            self.assertEqual(c.provider.api_key_env,'LEAFAPI_API_KEY')
            self.assertFalse(c.real_requests_authorized)
            self.assertEqual(dataset.opened,[])


if __name__=='__main__': unittest.main()
