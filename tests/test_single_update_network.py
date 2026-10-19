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

if __name__=='__main__':unittest.main()
