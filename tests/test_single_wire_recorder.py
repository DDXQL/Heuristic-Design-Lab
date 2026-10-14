"""Handcrafted recording-only fixtures; no real model/benchmark requests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from resume_single_settlement import WireRecorder,reconcile
from fjsp_usage.research_real.budget import BudgetStop


class Fake:
    config=None;identity='fake';secret='not-real';redact=staticmethod(str)
    calls=0
    def preflight(self,prompt):pass
    def dispatch(self,key,prompt,*,kind,on_sent):
        self.calls+=1;on_sent()
        return {'text':'handwritten local fixture, not a candidate','usage':{'input_tokens':2,'output_tokens':3}}


class RecorderTests(unittest.TestCase):
    def settlement_fixture(self,root,*,reason='supplier billing metadata unavailable; no settlement inferred',group='codex-deafult'):
        key='r201/B0/fixture';record={'status':'settled','send_confirmed':True,'before_used':100,
            'after_used':107,'observed_account_delta':7,'reserved':410000,'started_at':100,'finished_at':102}
        bill={'global_key':key,'status':'settlement_not_certified','original_quota_record':record,
            'before':{'success':True,'records':[]},'after':{'success':False,'http_status':429},
            'wire_usage':{'input_tokens':2,'output_tokens':3},'response_metadata':{'gateway_request_id':'fixture-id'}}
        folder=Path(root)/'billing';folder.mkdir();path=folder/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        path.write_text(json.dumps(bill));raw=path.read_bytes()
        invoice={'request_id':'fixture-id','model_name':'gpt-6.1-sol','created_at':101,'type':2,'quota':7,
            'prompt_tokens':2,'completion_tokens':3,'group':group}
        data={'halted':True,'stop_reason':reason,'records':{key:record},'latest_quota':{'total_used':107},'observed_at':103}
        quota=SimpleNamespace(data=data,transport=SimpleNamespace(secret='fixture'),check_retained=lambda:24000000,
            balance=lambda:None,save=lambda:None)
        flow=SimpleNamespace(directory=Path(root),config=SimpleNamespace(platform_quota_ceiling=30000000,
            provider=SimpleNamespace(model='gpt-6.1-sol')),ledger=SimpleNamespace(data={'halted':False}))
        return flow,quota,invoice,path,raw

    def test_exact_429_receipt_releases_native_hold_only_preserves_raw_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,quota,invoice,path,raw=self.settlement_fixture(tmp)
            with patch('resume_single_settlement.query_invoices',return_value={'success':True,'records':[invoice]}):
                proof=reconcile(flow,quota)
            self.assertFalse(quota.data['halted']);self.assertEqual(quota.check_retained(),24000000)
            self.assertEqual(proof['actual_platform_units'],7);self.assertTrue(proof['slot_remains_failed'])
            self.assertEqual(raw,path.read_bytes())
            self.assertEqual(quota.data['records'][proof['global_key']],proof['original_quota_record'])

    def test_other_budget_gate_and_wrong_group_cannot_be_unhalted(self):
        for reason,group in [('observed account debit exceeded reservation/ceiling','codex-deafult'),
                ('supplier billing metadata unavailable; no settlement inferred','wrong')]:
            with tempfile.TemporaryDirectory() as tmp:
                flow,quota,invoice,_,_=self.settlement_fixture(tmp,reason=reason,group=group)
                with patch('resume_single_settlement.query_invoices',return_value={'success':True,'records':[invoice]}),\
                        self.assertRaises(BudgetStop):reconcile(flow,quota)
                self.assertTrue(quota.data['halted'])

    def test_wire_reply_survives_downstream_metadata_failure_without_changing_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Fake();sent=[];checks=[]
            recorder=WireRecorder(base,tmp,lambda:checks.append(True))
            result=recorder.dispatch('r201/init/fixture','prompt',on_sent=lambda:sent.append(True))
            saved=json.loads(next(Path(tmp).glob('*.json')).read_text())
            self.assertEqual(result,saved['reply']);self.assertTrue(saved['send_confirmed'])
            self.assertEqual(base.calls,1);self.assertEqual(sent,[True]);self.assertTrue(checks)
            with self.assertRaises(BudgetStop):recorder.dispatch('r201/init/fixture','prompt')
            self.assertEqual(base.calls,1)

    def test_no_dispatch_when_recording_amendment_is_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Fake()
            def reject():raise BudgetStop('amendment changed')
            recorder=WireRecorder(base,tmp,reject)
            with self.assertRaises(BudgetStop):recorder.dispatch('one','prompt')
            self.assertEqual(base.calls,0)
            self.assertEqual(list(Path(tmp).glob('*.json')),[])


if __name__=='__main__':unittest.main()
