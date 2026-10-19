"""Handwritten settlement proofs; no network, provider or candidates."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.single_update import VERSION
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('network_proof',ROOT/'tools/reconcile_single_update_network.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class NetworkProofTest(unittest.TestCase):
    def fixture(self):
        key='r201/A/A/g0000/000009'
        c=NS(conditional_research={'version':VERSION,'risk_policy':{'group':'codex-deafult'},
            'history_binding':{'retained_account_hold':24000000}},real_requests_authorized=True,
            total_request_cap=60,seeds=(201,),platform_quota_ceiling=30000000,provider=NS(model='HANDWRITTEN_MODEL'))
        old={'status':'settlement_unknown','send_confirmed':True,'before_used':2000000,'reserved':410000,'started_at':1000,'finished_at':1050}
        q={'halted':True,'stop_reason':m.REASON,'records':{key:deepcopy(old)},'observed_used':2000000}
        n={'records':{key:{'send_confirmed':True,'status':'failed','usage':None}}}
        b={'status':'settlement_not_certified','settlement_error':m.REASON,'transport_status':'failed','wire_usage':None,
            'original_quota_record':old,'response_metadata':{'gateway_request_id':'HANDWRITTEN_ID'},'before':{'success':True,'records':[]}}
        w={'global_key':key,'send_confirmed':True,'status':'wire_failed','error':m.WIRE_ERROR}
        fresh={'success':True,'observed_at':1200,'quota':{'available':True,'unlimited_quota':False,
            'total_used':2000908,'total_granted':100000000,'total_available':97999092,'expires_at':0}}
        after={'success':True,'records':[{'model_name':'HANDWRITTEN_MODEL','request_id':'HANDWRITTEN_ID',
            'type':2,'created_at':1020,'quota':908,'group':'codex-deafult'}]}
        return [c,n,q,key,b,w,fresh,after]
    def test_exact_positive_invoice_and_debit_proves_without_mutating_originals(self):
        args=self.fixture();before=deepcopy(args)
        account,invoice=m.prove(*args,retained=24000000,now=1220)
        self.assertEqual(invoice['quota'],908);self.assertEqual(account['observed_account_delta'],908)
        self.assertEqual(args,before);self.assertEqual(args[1]['records'][args[3]]['usage'],None)
        self.assertTrue(args[2]['halted'])  # proof calculation alone never clears gate
    def test_genuine_observed_mismatch_remains_rejected(self):
        args=self.fixture();args[4]['original_quota_record'].update(status='settled',after_used=2000999,observed_account_delta=999)
        args[2]['records'][args[3]]=deepcopy(args[4]['original_quota_record'])
        with self.assertRaises(BudgetStop):m.prove(*args,retained=24000000,now=1220)
    def test_wrong_debit_id_group_model_and_zero_fee_fail(self):
        for change in ('debit','id','group','model','zero'):
            with self.subTest(change=change):
                a=self.fixture()
                if change=='debit':a[6]['quota'].update(total_used=2000909,total_available=97999091)
                if change=='id':a[7]['records'][0]['request_id']='OTHER_ID'
                if change=='group':a[7]['records'][0]['group']='OTHER_GROUP'
                if change=='model':a[7]['records'][0]['model_name']='OTHER_MODEL'
                if change=='zero':
                    a[7]['records'][0]['quota']=0;a[6]['quota'].update(total_used=2000000,total_available=98000000)
                with self.assertRaises(BudgetStop):m.prove(*a,retained=24000000,now=1220)
    def test_stale_proof_old_version_hold_release_and_changed_wire_fail(self):
        for change in ('stale','old_version','hold','wire'):
            with self.subTest(change=change):
                a=self.fixture();now=1220;hold=24000000
                if change=='stale':now=1400
                if change=='old_version':a[0].conditional_research['version']='old_batch'
                if change=='hold':hold=0
                if change=='wire':a[5]['error']='OTHER_FAILURE'
                with self.assertRaises(BudgetStop):m.prove(*a,retained=hold,now=now)

    def delayed_fixture(self):
        a=self.fixture();a[0].provider.read_timeout=10;a[0].provider.total_timeout=60
        old=a[4]['original_quota_record'];old.update(status='settled',after_used=old['before_used'],observed_account_delta=0)
        a[2]['records'][a[3]]=deepcopy(old);a[2]['stop_reason']='account quota unavailable/inconsistent; no retry'
        a[4]['response_metadata']={};a[5]['error']='TimeoutError'
        row=a[7]['records'][0];row.update(created_at=1055,prompt_tokens=100,completion_tokens=0,use_time=55)
        a[4]['after']=deepcopy(a[7]);return a

    def test_delayed_timeout_requires_invoice_created_after_original_snapshot(self):
        a=self.delayed_fixture();before=deepcopy(a)
        account,invoice=m.prove(*a,retained=24000000,now=1220)
        self.assertEqual(invoice['quota'],account['observed_account_delta']);self.assertEqual(a,before)
        self.assertGreater(invoice['created_at'],a[4]['original_quota_record']['finished_at'])

    def test_delayed_exception_rejects_real_mismatch_and_nonunique_receipts(self):
        for change in ('early_invoice','nonzero_original_debit','wrong_fresh_delta','nonunique','positive_output','short_duration'):
            with self.subTest(change=change):
                a=self.delayed_fixture()
                if change=='early_invoice':a[4]['after']['records'][0]['created_at']=1045
                if change=='nonzero_original_debit':
                    a[4]['original_quota_record'].update(after_used=2000001,observed_account_delta=1)
                    a[2]['records'][a[3]]=deepcopy(a[4]['original_quota_record'])
                if change=='wrong_fresh_delta':a[6]['quota'].update(total_used=2000909,total_available=97999091)
                if change=='nonunique':
                    other=deepcopy(a[4]['after']['records'][0]);other['request_id']='OTHER_ID';a[4]['after']['records'].append(other)
                if change=='positive_output':a[4]['after']['records'][0]['completion_tokens']=1
                if change=='short_duration':a[4]['after']['records'][0]['use_time']=1
                with self.assertRaises(BudgetStop):m.prove(*a,retained=24000000,now=1220)

if __name__=='__main__':unittest.main()
