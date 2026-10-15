"""Offline recovery evidence tests; fake metadata only, no inference transport."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

from tools.resume_usage_metadata import REASON, restore_metadata, verify_existing
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.budget import BudgetStop
from tools.reconcile_usage_429 import build_proof
from test_usage_v22_handoff_access import amendment_fixture


class RecoveryTests(unittest.TestCase):
    def test_new_429_proof_reuses_verified_schema_without_rewriting_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'own';key,old,_,_=amendment_fixture(p)
            billpath=p/'billing'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            bill=json.loads(billpath.read_text());before=billpath.read_bytes()
            qp=p/'Settlement.quota.json';ip=p/'Settlement.invoices.json'
            account=json.loads(qp.read_text());invoices=json.loads(ip.read_text())
            target,proof=build_proof(p,billpath,bill,account,invoices,qp,ip,'gpt-6.1-sol')
            self.assertTrue(proof['slot_remains_failed']);self.assertEqual(proof['actual_platform_units'],3)
            self.assertEqual(proof['research_run'],'own');self.assertEqual(billpath.read_bytes(),before)
            self.assertEqual(proof['original_quota_record'],old);self.assertFalse(target.exists())
            for field,value in [('quota',4),('model_name','wrong'),('group','wrong'),('created_at',180),('prompt_tokens',99)]:
                bad=deepcopy(invoices);bad['records'][0][field]=value;atomic_json(ip,bad)
                with self.assertRaises(BudgetStop):build_proof(p,billpath,bill,account,bad,qp,ip,'gpt-6.1-sol')

    def fixture(self, path, success=True):
        data = {'halted': True, 'stop_reason': REASON, 'records': {}}
        ledger = {'halted': False, 'records': {}}
        atomic_json(path / 'budget.json', ledger)
        quota = NS(data=data, transport=NS(secret='fake'), check_retained=lambda:24000000,
            tariff_query=lambda secret:{'model':'gpt-6.1-sol'},
            balance=lambda:{'total_used':10, 'total_available':99999990}, clock=lambda:1,
            save=lambda:atomic_json(path / 'quota.json', data))
        flow = NS(directory=path, ledger=NS(data=ledger), config=NS(provider=NS(model='gpt-6.1-sol')))
        client = NS(inner=NS(inner=quota, query=lambda:{'success':success,'records':[]}))
        guard = NS(check=lambda:None)
        return flow, client, guard, quota

    def test_healthy_read_only_proof_restores_without_changing_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); f,c,g,q=self.fixture(p); old=deepcopy(q.data['records'])
            proof=restore_metadata(f,c,g,driver_sha='fixture')
            self.assertFalse(q.data['halted']); self.assertEqual(q.data['records'],old)
            audit=json.loads(proof.read_text())
            self.assertTrue(audit['previous_quota']['halted'])
            self.assertEqual(audit['historical_hold_unchanged'],24000000)
            self.assertEqual(audit['inference_requests'],0)
            self.assertEqual(json.loads((p/'budget.json').read_text()),f.ledger.data)

    def test_failed_metadata_stays_halted_and_does_not_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);f,c,g,q=self.fixture(p,False)
            with self.assertRaises(BudgetStop): restore_metadata(f,c,g,driver_sha='fixture')
            self.assertTrue(q.data['halted']);self.assertEqual(f.ledger.data['records'],{})
            self.assertEqual(json.loads(next(p.glob('Metadata_health*')).read_text())['status'],'still_blocked_no_inference')

    def test_other_gate_and_foreign_writer_fail_before_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            f,c,g,q=self.fixture(Path(tmp));q.data['stop_reason']='uncertain interrupted request'
            c.inner.query=lambda:self.fail('metadata should not be reached')
            with self.assertRaises(BudgetStop):restore_metadata(f,c,g,driver_sha='fixture')
            q.data['stop_reason']=REASON
            def blocked():raise BudgetStop('peer writer active')
            g.check=blocked
            with self.assertRaises(BudgetStop):restore_metadata(f,c,g,driver_sha='fixture')
            self.assertTrue(q.data['halted'])

    def test_pending_sent_or_unmatched_ledger_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            with self.assertRaises(BudgetStop):verify_existing(p,{'halted':False,'records':{'key':{}}},{'records':{}},'gpt-6.1-sol')

    def test_receipts_matched_independently_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);key='r301/init/INIT/init/000000'
            account={'status':'settled','send_confirmed':True,'reserved':100,
                'before_used':10,'after_used':13,'observed_account_delta':3,'started_at':100,'finished_at':110}
            invoice={'request_id':'supplier','model_name':'gpt-6.1-sol','created_at':105,'type':2,'quota':3}
            bill={'global_key':key,'status':'invoice_account_matched','transport_status':'completed',
                'original_quota_record':account,'wire_usage':{'input_tokens':2,'output_tokens':1},
                'before':{'success':True,'records':[]},'after':{'success':True,'records':[invoice]},
                'invoice':invoice,'actual_platform_units':3}
            path=p/'billing'/(hashlib.sha256(key.encode()).hexdigest()+'.json');atomic_json(path,bill)
            ledger={'halted':False,'records':{key:{'send_confirmed':True,'status':'completed','usage':bill['wire_usage']}}}
            quota={'records':{key:account}}
            self.assertEqual(len(verify_existing(p,ledger,quota,'gpt-6.1-sol')),1)
            for field,value in [('actual_platform_units',0),('global_key','other'),('wire_usage',None)]:
                changed=deepcopy(bill);changed[field]=value;atomic_json(path,changed)
                with self.assertRaises(BudgetStop):verify_existing(p,ledger,quota,'gpt-6.1-sol')
            atomic_json(path,bill);quota['records'][key]={**account,'status':'pending'}
            with self.assertRaises(BudgetStop):verify_existing(p,ledger,quota,'gpt-6.1-sol')


if __name__=='__main__':unittest.main()
