"""Execution acceptance: mock API + toy kernel + detached control. No formal data."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import validate_code,U_ARGS,H_ARGS
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.attempt_budget import AttemptJournal
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.real_transport import TransportError
from fjsp_usage.usage_v2 import VERSION
from tools import cross_feedback_ab_execute as x
from tests.test_baseline_a import toy
from tests import test_baseline_supplemental as t30_fixtures


class MockTransport:
    identity='synthetic-no-inference'
    redact=staticmethod(str)
    def __init__(self,path,failures=0):self.directory=Path(path);self.calls=[];self.failures=failures
    def preflight(self,prompt):pass
    def dispatch(self,key,prompt,*,kind,on_sent):
        self.calls.append(key);on_sent()
        if len(self.calls)<=self.failures:
            e=TransportError('synthetic temporary');e.metadata={'http_status':503};raise e
        return {'text':'COMPLETE BUT INVALID SOURCE','usage':{'input_tokens':7,'output_tokens':9},'metadata':{'model':'mock'}}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        p=patch('socket.socket.connect',side_effect=AssertionError('NO REAL NETWORK'));p.start();self.addCleanup(p.stop)
        p=patch('fjsp_usage.research_real.real_transport.JsonCandidateTransport.dispatch',side_effect=AssertionError('NO REAL API'));p.start();self.addCleanup(p.stop)
        self.p={'provider':{'endpoint':'https://leafapi.cc/v1/chat/completions','model':'gpt-6.1-sol',
            'protocol':'openai-chat-v1','api_key_env':'LEAFAPI_API_KEY','max_output_tokens':8192}}

    def journal(self,transport):
        return AttemptJournal(self.root/'requests.json',config=x.config(self.p),context='synthetic',
            phase='mock',transport=transport,sleep=lambda t:None)

    def test_waiver_configuration_keeps_request_caps_no_money_gate(self):
        c=x.config(self.p)
        self.assertEqual(c.provider.payload() if hasattr(c.provider,'payload') else asdict(c.provider),asdict(x.ProviderConfig(**self.p['provider'])))
        self.assertEqual(c.total_request_cap,30);self.assertEqual(c.request_budget['api_attempt_cap'],40)
        self.assertEqual(c.request_budget['per_candidate_attempt_cap'],2)
        self.assertIsNone(c.cost_cap_estimate);self.assertIsNone(c.platform_quota_ceiling)

    def test_complete_response_never_regenerated_for_bad_source(self):
        t=MockTransport(self.root);j=self.journal(t);r=j.request('q','prompt')
        self.assertEqual(r['status'],'completed');self.assertEqual(len(t.calls),1)
        self.assertEqual(self.journal(t).request('q','prompt')['text'],'COMPLETE BUT INVALID SOURCE')
        self.assertEqual(len(t.calls),1)

    def test_config_JSON_roundtrip_has_same_identity(self):
        payload=x.config(self.p).payload()
        self.assertEqual(digest(payload),digest(json.loads(json.dumps(payload))))

    def test_evidenced_transient_retry_only_twice(self):
        t=MockTransport(self.root,failures=1);j=self.journal(t)
        self.assertEqual(j.request('q','prompt')['status'],'completed');self.assertEqual(len(t.calls),2)
        self.assertEqual(j.attempt_count,2)

    def test_two_failures_no_refill_and_global_40_attempt_cap(self):
        t=MockTransport(self.root,failures=100);j=self.journal(t)
        for i in range(20):self.assertEqual(j.request(str(i),'p')['status'],'failed')
        self.assertEqual(j.attempt_count,40)
        with self.assertRaises(BudgetStop):j.request('extra','p')
        self.assertEqual(len(t.calls),40)

    def test_unknown_delivery_preserved_not_resent(self):
        t=MockTransport(self.root);j=self.journal(t)
        key='q';aid='mock/q/attempt/01';pk=digest({'prompt':'p','kind':'U'})
        j.data['requests'][key]={'status':'pending','prompt':'p','prompt_key':pk,'kind':'U','global_key':'mock/q','logical_id':key,'attempt_ids':[aid],'usage':None}
        j.data['api_attempts'][aid]={'id':aid,'logical_id':key,'number':1,'status':'pending','send_confirmed':False,'prompt_key':pk,'started_at':time.time(),'usage':None}
        j.save();j.request(key,'p')
        self.assertEqual(t.calls,[]);self.assertEqual(j.data['api_attempts'][aid]['status'],'interrupted_unknown')
        self.assertEqual(j.data['halt_reason'],'uncertain_dispatch_requires_review')

    def test_deadline_prevents_another_attempt(self):
        t=MockTransport(self.root);d=x.DeadlineTransport(t,time.time()-1)
        with self.assertRaises(BudgetStop):d.preflight('p')
        self.assertEqual(t.calls,[])

    def test_unknown_evaluation_reservation_stop(self):
        state={'cursor':0,'tasks':{},'evaluations':{'key':{'status':'reserved'}}}
        with self.assertRaisesRegex(BudgetStop,'unknown evaluation'):x.validate_state(state,[])

    def test_same_T30_success_and_identity_protection(self):
        result,kwargs=t30_fixtures.T30Tests().evidence()
        self.assertEqual(x.certify(result,kwargs)['decision'],'accepted')
        kwargs['after']['identity']='bad'
        self.assertEqual(x.certify(result,kwargs)['decision'],'stop')

    def test_runtime_invalid_requires_normal_exit_identity_not_prefix_score(self):
        result,k=t30_fixtures.T30Tests().evidence();result.update(valid=False,fitness=None,instances=[],error_type='UsageOutputError')
        k['lifecycle'].update(rows_received=0,expected_rows=21,all_results_received=False,exit_grace_used=False)
        self.assertEqual(x.certify(result,k)['decision'],'candidate_invalid_continue')
        k['lifecycle']['exitcode']=-15
        self.assertEqual(x.certify(result,k)['decision'],'stop')

    def test_formal_worker_uses_same_kernel_two_toy_solves(self):
        hcode='def priority('+', '.join(H_ARGS)+'):\n    return -processing_time\n'
        h=validate_code(hcode,kind='h');vector=repr((.5,.5)+tuple(0. for _ in range(8)))
        u=validate_code('def use_heuristics('+', '.join(U_ARGS)+'):\n    return (1, '+vector+')\n',interface_version=VERSION,member_count=10)
        modules={'synthetic':{'code':'toy'}};w={'pid':os.getpid(),'modules':modules,'identity':digest(modules)}
        class Pipe:
            rows=[]
            def send(self,row):self.rows.append(deepcopy(row))
            def close(self):pass
        pipe=Pipe()
        with patch.object(x,'witness',return_value=w),patch.object(x.s.v2,'local_guard',return_value={'network_attempts_blocked':0,'nontrain_opens_blocked':0}):
            x.worker(pipe,{'folder':str(self.root),'binding':{},'candidate':asdict(u),'train_paths':[]},[h]*10,[toy()],['SYNTHETIC'],(0,1))
        self.assertEqual(len(pipe.rows),1);row=pipe.rows[0]
        self.assertNotIn('error',row);self.assertEqual(row['captured_solves'],2)
        self.assertEqual(row['single_h_calls'],row['recheck_h_calls'])
        self.assertEqual(row['physical_schedule_sha256'],row['recheck_physical_schedule_sha256'])
        self.assertTrue((self.root/'before.json').exists());self.assertTrue((self.root/'after.json').exists())

    def test_detached_child_survives_launcher_exit(self):
        marker=self.root/'done.json';log=self.root/'log'
        child='import os,json,time;from pathlib import Path;time.sleep(.3);Path('+repr(str(marker))+').write_text(json.dumps({"pid":os.getpid(),"sid":os.getsid(0)}))'
        launcher='from tools.cross_feedback_ab_execute import detach;print(detach('+repr([sys.executable,'-B','-c',child])+','+repr(str(log))+'))'
        reply=subprocess.run([sys.executable,'-B','-c',launcher],env={**os.environ,'PYTHONPATH':str(x.ROOT/'code')+':'+str(x.ROOT),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=8)
        self.assertEqual(reply.returncode,0,reply.stderr);pid=int(reply.stdout.strip())
        until=time.monotonic()+3
        while not marker.exists() and time.monotonic()<until:time.sleep(.05)
        self.assertTrue(marker.exists());record=json.loads(marker.read_text())
        self.assertEqual(record['pid'],pid);self.assertEqual(record['sid'],pid)

    def test_child_guard_blocks_simulated_network_and_nontrain_events(self):
        script='''import sys,json
from tools.fusion_v2_experiment import local_guard
g=local_guard([])
for event,args in [('socket.connect',(None,('SYNTHETIC',0))),('open',('/SYNTHETIC/not_allowed.fjsp','r',0))]:
 try:sys.audit(event,*args)
 except RuntimeError:pass
print(json.dumps(g))
'''
        r=subprocess.run([sys.executable,'-B','-c',script],capture_output=True,text=True,timeout=8,
            env={**os.environ,'PYTHONPATH':str(x.ROOT/'code')+':'+str(x.ROOT),'PYTHONDONTWRITEBYTECODE':'1'})
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout),{'network_attempts_blocked':1,'nontrain_opens_blocked':1})


if __name__=='__main__':unittest.main()
