"""A missing wire/header must not become invented tokens or a zero fee."""
from copy import deepcopy
import unittest
from tools.settle_unique_failed_usage import close_fee
from fjsp_usage.research_real.budget import BudgetStop


class FailedFeeTests(unittest.TestCase):
    def fixture(self):
        old={'status':'settlement_unknown','send_confirmed':True,'started_at':100,
            'finished_at':10000,'before_used':10,'reserved':100}
        bill={'wire_usage':None,'transport_status':'failed','before':{'success':True,'records':[]},
            'response_metadata':{'provider_roundtrip_seconds':100}}
        wire={'status':'wire_failed','error':'TimeoutError','usage':None}
        account={'success':True,'inference_requests':0,'observed_at':10001,
            'quota':{'unlimited_quota':False,'total_used':13,'total_available':987,'total_granted':1000}}
        invoices={'success':True,'records':[{'request_id':'unique-supplier','created_at':150,
            'model_name':'gpt-6.1-sol','type':2,'quota':3,'group':'codex-deafult'}]}
        return old,bill,wire,account,invoices

    def test_unique_invoice_debit_closes_fee_without_wire_tokens_or_header(self):
        old,bill,wire,account,invoices=self.fixture();before=deepcopy(old)
        closed,invoice=close_fee(old,bill,wire,account,invoices,'gpt-6.1-sol')
        self.assertEqual(closed['observed_account_delta'],3);self.assertEqual(invoice['quota'],3)
        self.assertEqual(old,before);self.assertIsNone(wire['usage']);self.assertNotIn('gateway_request_id',bill['response_metadata'])

    def test_absent_ambiguous_wrong_window_group_model_or_account_rejected(self):
        for change in ('absent','ambiguous','window','group','model','account','reserve','wire'):
            with self.subTest(change=change):
                old,bill,wire,account,invoices=self.fixture()
                if change=='absent':invoices['records']=[]
                elif change=='ambiguous':invoices['records'].append({**invoices['records'][0],'request_id':'second'})
                elif change=='window':invoices['records'][0]['created_at']=300
                elif change=='group':invoices['records'][0]['group']='wrong'
                elif change=='model':invoices['records'][0]['model_name']='wrong'
                elif change=='account':account['quota'].update(total_used=14,total_available=986)
                elif change=='reserve':old['reserved']=2
                else:wire['status']='pending'
                with self.assertRaises(BudgetStop):close_fee(old,bill,wire,account,invoices,'gpt-6.1-sol')


if __name__=='__main__':unittest.main()
