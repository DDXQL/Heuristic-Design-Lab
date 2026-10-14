"""Only metadata scope and risk arithmetic; no benchmark or provider requests."""
import importlib.util
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audit_single',ROOT/'tools/audit_single_settlement.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_private_log_content_excluded_and_pricing_scope_kept(self):
        body={'success':True,'data':{'total':1,'items':[{'id':1,'request_id':'one','created_at':123,
            'model_name':'model','quota':7,'content':'private error','api_key':'private',
            'other':json.dumps({'group_ratio':.5,'billing_mode':'tiered_expr','private_key':'private'})}]}}
        result=audit.extract(body,'logs')
        self.assertEqual(result['pagination_metadata']['total'],1)
        self.assertEqual(result['records'][0]['pricing_metadata'],{'group_ratio':.5,'billing_mode':'tiered_expr'})
        self.assertNotIn('private',json.dumps(result))

    def test_secrets_in_values_and_keys_are_redacted(self):
        self.assertEqual(audit.sanitize({'secret':['secret']},'secret'),{'[REDACTED]':['[REDACTED]']})

    def test_only_known_get_paths_and_no_secret_in_url(self):
        for path in ('https://other.invalid/api/log/token','/v1/chat/completions','/api/log/token?key=private'):
            with self.assertRaises(ValueError):audit.get_metadata('private',path,'logs')

    def test_http_query_get_headers_ids_not_original_post_ids(self):
        calls=[]
        class Response:
            status=200
            def getheader(self,key):return 'metadata-id' if key=='x-oneapi-request-id' else None
            def read(self,bound):return b'{"success":true,"data":[]}'
        class Connection:
            def __init__(self,*a,**k):pass
            def request(self,*a,**k):calls.append((a,k))
            def getresponse(self):return Response()
            def close(self):pass
        result=audit.get_metadata('private','/api/log/token?p=2','logs',connection_factory=Connection)
        self.assertEqual(calls[0][0][0],'GET')
        self.assertNotIn('private',json.dumps(result));self.assertEqual(result['inference_requests'],0)
        self.assertIn('not the failed POST',result['response_headers_scope'])

    def test_known_key_missing_model_is_not_route_confirmation(self):
        result=audit.extract({'success':True,'data':[{'id':'other-model'}]},'models')
        self.assertFalse(result['locked_model_listed'])
        compatible=audit.extract({'object':'list','data':[{'id':'gpt-5.6-sol'}]},'models')
        self.assertTrue(compatible['success']);self.assertTrue(compatible['locked_model_listed'])

    def test_risk_arithmetic_preserves_unknown_status_and_cumulative_ceiling(self):
        old=audit.engineering_reservation(5789+4096,32768)
        self.assertEqual(old['raw_conditional_points'],4394836.875)
        next_request=audit.engineering_reservation(65536,32768)
        self.assertEqual(next_request['proposed_next_request_reservation'],7900000)
        self.assertEqual(1557783+12000000+5000000+7900000,26457783)
        self.assertFalse(next_request['certified_provider_upper_bound'])

    def test_large_prompt_is_rejected_instead_of_capping_underestimated_risk(self):
        result=audit.engineering_reservation(266240,32768)
        self.assertFalse(result['within_original_12000000_per_request_max'])
        for value in (True,-1):
            with self.assertRaises(ValueError):audit.engineering_reservation(value,32768)
        with self.assertRaises(ValueError):audit.engineering_reservation(1,2,group_ratio=float('inf'))


if __name__=='__main__':unittest.main()
