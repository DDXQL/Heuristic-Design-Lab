"""Synthetic supplemental receipts and failed metadata; never inference traffic."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fjsp_usage.research_real.budget import BudgetStop, BudgetLedger, BudgetJournal
from fjsp_usage.research_real.quota_guard import QuotaGuardedTransport
from fjsp_usage.usage_v2.billing import certified_reconciliation, InvoiceTransport
from fjsp_usage.usage_v2.registration import audit_final_handoff, file_hash
from fjsp_usage.usage_v2.access import WireRecorder, MetadataPacer, InvoicePacer
from test_platform_quota_guard import FakeTransport, quota
from test_usage_v22_registration import save


def amendment_fixture(directory):
    run = directory.name; key = 'r201/init/request'; name = hashlib.sha256(key.encode()).hexdigest()
    old = {'status':'settlement_unknown', 'before_used':10, 'reserved':100,
           'send_confirmed':True, 'started_at':100, 'finished_at':110}
    usage = {'input_tokens':2, 'output_tokens':1}
    invoice = {'request_id':'supplier-id', 'created_at':105, 'model_name':'gpt-6.1-sol',
        'type':2, 'quota':3, 'prompt_tokens':2, 'completion_tokens':1, 'group':'codex-deafult'}
    bill = {'global_key':key, 'before':{'success':True, 'records':[]},
        'original_quota_record':old, 'wire_usage':usage,
        'response_metadata':{'gateway_request_id':'supplier-id'}, 'status':'settlement_not_certified'}
    save(directory/'billing'/f'{name}.json', bill)
    save(directory/'Settlement.quota.json', {'success':True, 'inference_requests':0, 'observed_at':200,
        'quota':{'total_used':13,'total_available':987,'total_granted':1000}})
    save(directory/'Settlement.invoices.json', {'success':True,'records':[invoice]})
    proof = {'version':'single-ID-nonsemantic-recording-settlement-amendment-v1-20261014',
        'global_key':key, 'original_quota_record':old, 'supplier_request_id':'supplier-id',
        'original_billing_sha256':file_hash(directory/'billing'/f'{name}.json'), 'invoice':invoice,
        'reconciled_account':{**old,'status':'settled','after_used':13,'observed_account_delta':3,'finished_at':200},
        'actual_platform_units':3, 'wire_usage':usage, 'slot_remains_failed':True,
        'evidence_files_sha256':{n:file_hash(directory/n) for n in ('Settlement.quota.json','Settlement.invoices.json')}}
    save(directory/'Settlement_resume_proof.json',proof)
    def bundle():
        docs={run+'/'+str(p.relative_to(directory)):json.loads(p.read_text()) for p in directory.rglob('*.json')}
        hashes={run+'/'+str(p.relative_to(directory)):file_hash(p) for p in directory.rglob('*.json')}
        return docs,hashes
    return key,old,proof,bundle


class HandoffTests(unittest.TestCase):
    def test_supplemental_receipt_settles_immutable_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'peer';key,old,proof,bundle=amendment_fixture(p);before=deepcopy(old)
            docs,hashes=bundle()
            result=certified_reconciliation(key,old,[proof],docs,p.name,'gpt-6.1-sol',hashes)
            self.assertEqual(result['quota'],3);self.assertEqual(old,before)
            self.assertEqual(old['status'],'settlement_unknown')

    def test_changed_hash_supplier_model_window_or_account_rejected(self):
        for change in ('hash','supplier','model','window','account','amount','missing_proof','usage'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'peer';key,old,proof,bundle=amendment_fixture(p);docs,hashes=bundle()
                if change=='hash':hashes[p.name+'/Settlement.quota.json']='other'
                if change=='supplier':proof['supplier_request_id']='other'
                if change=='model':proof['invoice']['model_name']='other'
                if change=='window':proof['invoice']['created_at']=150
                if change=='account':proof['reconciled_account']['before_used']=11
                if change=='amount':proof['actual_platform_units']=4
                if change=='missing_proof':docs.pop(p.name+'/Settlement_resume_proof.json')
                if change=='usage':proof['wire_usage']['input_tokens']=99
                if change not in ('hash','missing_proof'):docs[p.name+'/Settlement_resume_proof.json']=proof
                with self.assertRaises((BudgetStop,ValueError)):
                    certified_reconciliation(key,old,[proof],docs,p.name,'gpt-6.1-sol',hashes)

    def test_final_totals_come_from_request_proofs_and_proved_unsent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'peer';key,old,proof,bundle=amendment_fixture(p)
            unsent='r201/B1/request';name=hashlib.sha256(unsent.encode()).hexdigest()
            budget={'identity':'fixture','records':{key:{'status':'failed','send_confirmed':True,'usage':proof['wire_usage']},
                unsent:{'status':'failed','send_confirmed':False,'usage':None}}}
            save(p/'budget.json',budget)
            quota_body={'halted':False,'observed_used':13,'records':{key:old},'invoice_reconciliations':[proof]}
            save(p/'billing'/f'{name}.json',{'status':'before_dispatch','before':{'success':False}})
            save(p/'requests.json',{'requests':{'u':{'global_key':unsent,'error':'cannot inspect supplier billing before dispatch'}}})
            handoff={'real_caller_active':False,'budget_identity':'fixture','budget_sha256':file_hash(p/'budget.json'),
                'quota_halted':False,'registered_generation_phases_complete':True,'known_new_points':3,
                'unknown_new_fee_keys':[],'unknown_new_fee_holds':0,'latest_verified_used_points':13,
                'old_account_hold':24000000,'summary':{'request_slots':2,'confirmed_sends':1}}
            save(p/'Final_budget_handoff.json',handoff)
            r=audit_final_handoff(p,budget,quota_body,'gpt-6.1-sol')
            self.assertEqual((r['actual_points'],r['proved_unsent']),(3,1))
            handoff['known_new_points']=0;save(p/'Final_budget_handoff.json',handoff)
            with self.assertRaises(BudgetStop):audit_final_handoff(p,budget,quota_body,'gpt-6.1-sol')


class AccessTests(unittest.TestCase):
    def test_full_reply_written_before_failed_account_get_and_no_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);wire=FakeTransport();wire.secret='fixture-only'
            recorded=WireRecorder(wire,p/'wire');values=iter((quota(10),{'error':'metadata unavailable'}))
            g=QuotaGuardedTransport(recorded,p/'quota.json','fixture',query=lambda:next(values),clock=lambda:0,sleep=lambda n:None)
            with self.assertRaises(BudgetStop):g.dispatch('request','prompt')
            r=json.loads(next((p/'wire').glob('*.json')).read_text())
            self.assertEqual(r['status'],'wire_completed_before_settlement')
            self.assertEqual(r['reply']['text'],'candidate');self.assertEqual(wire.calls,1)
            with self.assertRaises(BudgetStop):recorded.dispatch('request','prompt')
            self.assertEqual(wire.calls,1)

    def test_failed_before_send_invoice_get_consumes_no_later_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);wire=FakeTransport();g=QuotaGuardedTransport(wire,p/'quota.json','fixture',query=lambda:quota(10))
            count=[]
            def unavailable():count.append(1);return {'success':False,'http_status':429}
            invoice=InvoiceTransport(g,p/'billing',query=unavailable)
            ledger=BudgetLedger(p/'budget.json',wire.config,'fixture')
            journal=BudgetJournal(p/'journal.json',phase='H/init',cap=3,transport=invoice,ledger=ledger)
            for key in ('first','second'):
                with self.assertRaises(BudgetStop):journal.request(key,'prompt')
            self.assertEqual(len(ledger.data['records']),0);self.assertEqual(wire.calls,0);self.assertEqual(count,[1])

    def test_metadata_pacing_persists_and_invoice_spacing_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);now=[1000.0];ticks=[]
            def sleep(n):now[0]+=n
            metadata=MetadataPacer(p/'metadata.json',clock=lambda:now[0],sleep=sleep)
            query=InvoicePacer(lambda:ticks.append(now[0]) or {'success':True},p/'invoice.json',metadata,
                clock=lambda:now[0],sleep=sleep)
            query();metadata.call('/api/status',lambda:None);query()
            self.assertEqual(ticks,[1000,1075])
            reloaded=MetadataPacer(p/'metadata.json',clock=lambda:now[0],sleep=sleep)
            reloaded.call('/v1/models',lambda:None);self.assertEqual(now[0],1090)


if __name__=='__main__':unittest.main()
