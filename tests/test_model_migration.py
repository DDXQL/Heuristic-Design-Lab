"""Handcrafted local migration/transport/risk fixtures; no provider requests."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from test_conditional_research import setup
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.research_real.conditional_research import MIGRATION_VERSION,check_origin,history_summary
from fjsp_usage.research_real.model_migration import (VERSION,MODEL,EXPRESSION,DIAGNOSTIC_PROMPT,
    risk_reservation,check_live_tariff,MigrationQuota)
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.real_transport import _wire_worker


def declaration():
    return {'version':VERSION,'retired_run':'retired','retired_model':'gpt-5.6-sol','new_model':MODEL,
        'authorization_reviewer':'DDXQL','retirement':'MODEL_ACCESS_FAILURE_ABORTED_UNUSED_59_AUTHORIZATION_RETIRED',
        'diagnostic':{'cap':1,'max_output_tokens':256,'prompt':DIAGNOSTIC_PROMPT,'candidate':False,'retry':False},
        'preflight_run':'preflight','risk_policy':{'basis':'conditional-engineering-envelope-not-certified-provider-bound',
            'expression':EXPRESSION,'max_input_rate':5,'max_output_rate':15,'group':'codex-deafult',
            'group_ratio':0.5,'quota_per_unit':500000,'safety_factor':2,'round_to_points':1000,
            'input_envelope_rule':'max(65536,utf8_prompt_bytes+4096)',
            'output_envelope':32768,'max_per_request_points':1000000}}


def migrated_fixture(root):
    flow,_,_=setup(root);d=deepcopy(flow.config.conditional_research)
    d.update(version=MIGRATION_VERSION,model_migration=declaration())
    old=json.loads((root/'runs/target/protocol.json').read_text())
    identity=digest({'config':old['config'],'context':digest(old)})
    retired=root/'runs/retired';retired.mkdir()
    atomic_json(retired/'protocol.json',old)
    atomic_json(retired/'budget.json',{'identity':identity,'records':{'failed':{
        'status':'failed','send_confirmed':True,'usage':None,'reservation':{'input_tokens':65536,'output_tokens':32768}}}})
    # Distinct context is needed to avoid the intentional double-count guard.
    old['migration_fixture_only']=True;atomic_json(retired/'protocol.json',old)
    b=json.loads((retired/'budget.json').read_text());b['identity']=digest({'config':old['config'],'context':digest(old)})
    atomic_json(retired/'budget.json',b)
    atomic_json(retired/'platform_quota.json',{'identity':b['identity'],'observed_used':1500000,
        'records':{'failed':{'reserved':12000000,'started_at':500,'finished_at':501}}})
    pre=root/'runs/preflight';pre.mkdir()
    for name,body in {'pricing':{'success':True,'models':[{'billing_expr':EXPRESSION,'enable_groups':['codex-deafult']}],
            'group_ratio':{'codex-deafult':0.5}},'models':{'locked_model_listed':True},
            'status':{'public_fields':{'quota_per_unit':500000}}}.items():atomic_json(pre/(name+'.json'),body)
    for p in (retired,pre):
        for file in p.glob('*.json'):d['source_files_sha256'][str(file.relative_to(root/'runs'))]=hashlib.sha256(file.read_bytes()).hexdigest()
    d['history_batches'].append('retired')
    c=replace(flow.config,conditional_research=d,seeds=(201,),total_request_cap=61,
        platform_quota_reservation=1000000,phase_request_caps=None,
        provider=replace(flow.config.provider,model=MODEL,expected_response_model=MODEL))
    return flow,c


class MigrationTests(unittest.TestCase):
    def test_model_only_change_and_old_invoices_keep_old_model_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,c=migrated_fixture(Path(tmp))
            check_origin(flow.project_root,c,flow.dataset)
            audit=history_summary(flow.project_root,c)
            self.assertEqual(audit['historical_request_slots'],7)
            self.assertEqual(audit['retained_account_hold'],24000000)
            self.assertEqual(audit['unknown_requests'][-1]['wire_usage'],None)
            with self.assertRaisesRegex(ValueError,'only model'):
                check_origin(flow.project_root,replace(c,provider=replace(c.provider,max_output_tokens=2048)),flow.dataset)
            with self.assertRaises(ValueError):replace(c,total_request_cap=62)
            self.assertEqual(c.phase_caps()['r201/diagnostic'],1)

    def test_rate_math_cache_maximum_buffer_and_prompt_growth(self):
        p=declaration()['risk_policy']
        self.assertEqual(risk_reservation('short',p)['points'],410000)
        self.assertFalse(risk_reservation('short',p)['certified_provider_upper_bound'])
        self.assertGreater(risk_reservation('x'*100000,p)['points'],410000)
        with self.assertRaises(BudgetStop):risk_reservation('x'*400000,p)

    def test_live_tariff_model_and_group_change_are_closed(self):
        bodies={'/api/pricing':{'success':True,'data':[{'model_name':MODEL,'billing_expr':EXPRESSION,
            'enable_groups':['codex-deafult']}],'group_ratio':{'codex-deafult':0.5}},
            '/api/status':{'success':True,'data':{'quota_per_unit':500000}},'/v1/models':{'data':[{'id':MODEL}]}}
        query=lambda secret,path,**kw:deepcopy(bodies[path])
        self.assertEqual(check_live_tariff('unused',query=query)['model'],MODEL)
        bodies['/api/pricing']['group_ratio']['codex-deafult']=5.5
        with self.assertRaises(BudgetStop):check_live_tariff('unused',query=query)

    def test_two_old_holds_preserved_unknown_new_send_still_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,c=migrated_fixture(Path(tmp));c=replace(c,platform_quota_query_interval=.001)
            class T:
                config=c;identity='toy';secret='unused';redact=staticmethod(str)
                def preflight(self,prompt):pass
                def dispatch(self,key,prompt,*,kind,on_sent):
                    on_sent();return {'text':'toy','usage':None}
            def quota(used):return {'quota':{'available':True,'total_used':used,'total_available':100000000-used,
                'total_granted':100000000,'unlimited_quota':False,'expires_at':0}}
            g=MigrationQuota(T(),Path(tmp)/'newquota.json','toy',retained_extra=24000000,
                query=lambda:quota(1557783),tariff_query=lambda secret:{'toy':True})
            g.preflight('short')
            self.assertEqual(g.check_retained(),24000000)
            g.dispatch('r201/diagnostic/access/000000','short')
            self.assertEqual(g.data['records']['r201/diagnostic/access/000000']['reserved'],410000)
            self.assertTrue(g.data['halted'])
            self.assertEqual(g.check_retained(),24000000)
            with self.assertRaises(BudgetStop):g.preflight('next')
            other=MigrationQuota(T(),Path(tmp)/'closed.json','toy',retained_extra=24000000,
                query=lambda:quota(5600000),tariff_query=lambda secret:{'toy':True})
            with self.assertRaises(BudgetStop):other.preflight('short')

    def test_503_retains_gateway_id_status_sanitized_cause_no_credentials(self):
        class Pipe:
            def __init__(self):self.messages=[]
            def send(self,x):self.messages.append(x)
            def close(self):pass
        class Response:
            status=503
            def getheader(self,k):return {'x-oneapi-request-id':'supplier-abc','date':'Wed'}.get(k)
            def read(self,n):return json.dumps({'error':{'code':'no_channel','message':'unavailable secret-fixture Bearer abc'}}).encode()
        class Connection:
            sock=SimpleNamespace(settimeout=lambda x:None)
            def __init__(self,*args,**kw):pass
            def connect(self):pass
            def request(self,*args,**kw):pass
            def getresponse(self):return Response()
            def close(self):pass
        pipe=Pipe();provider=ProviderConfig('http://localhost/chat','fixture')
        with patch('fjsp_usage.research_real.real_transport.http.client.HTTPConnection',Connection):
            _wire_worker(pipe,provider,{'model':'fixture'},'secret-fixture')
        error=pipe.messages[-1];self.assertEqual(error['kind'],'error')
        self.assertEqual(error['metadata']['gateway_request_id'],'supplier-abc')
        self.assertEqual(error['metadata']['http_status'],503)
        self.assertEqual(error['metadata']['error_code'],'no_channel')
        self.assertNotIn('secret-fixture',json.dumps(pipe.messages))
        self.assertNotIn('Bearer abc',json.dumps(pipe.messages))
        self.assertIsNone(error['usage'])


if __name__=='__main__':unittest.main()
