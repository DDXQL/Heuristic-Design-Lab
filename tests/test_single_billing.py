"""Local invoice fixtures; no account access or paid generation."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from fjsp_usage.research_real.single_billing import match_invoice, InvoiceTransport
from fjsp_usage.research_real.budget import BudgetStop


def invoice(quota=7, identifier='new',kind=2):
    return {'request_id':identifier,'model_name':'model','created_at':101,'type':kind,'quota':quota}


def proof(rows):return {'success':True,'records':rows}


def account(delta=7):return {'status':'settled','send_confirmed':True,'started_at':100,
                             'finished_at':102,'before_used':100,'after_used':100+delta,'observed_account_delta':delta}


class MatchTests(unittest.TestCase):
    def test_unique_new_invoice_exact_debit(self):
        row=invoice();self.assertEqual(match_invoice(proof([invoice(identifier='old')]),proof([row]),account(),'model',failed=False),row)

    def test_previous_invoice_cannot_settle_new_failure(self):
        row=invoice()
        with self.assertRaises(BudgetStop):match_invoice(proof([row]),proof([row]),account(),'model',failed=True)

    def test_missing_duplicate_wrong_model_wrong_time_and_debit_stop(self):
        for rows in ([],[invoice(),invoice(identifier='other')],[{**invoice(),'model_name':'wrong'}],
                     [{**invoice(),'created_at':500}],[invoice(8)]):
            with self.subTest(rows=rows),self.assertRaises(BudgetStop):
                match_invoice(proof([]),proof(rows),account(),'model',failed=True)

    def test_final_zero_failure_receipt_is_evidence_not_missing_usage(self):
        self.assertEqual(match_invoice(proof([]),proof([invoice(0,kind=5)]),account(0),'model',failed=True)['quota'],0)

    def test_unavailable_or_pending_account_stops(self):
        for before,a in (({'success':False},account()),(proof([]),{**account(),'status':'settlement_unknown'})):
            with self.assertRaises(BudgetStop):match_invoice(before,proof([invoice()]),a,'model',failed=True)


class FakeQuota:
    identity='fixture';redact=staticmethod(lambda x:x)
    config=SimpleNamespace(provider=SimpleNamespace(model='model'))
    def __init__(self,failed=False,unknown=False,delta=7):
        self.failed,self.unknown,self.delta=failed,unknown,delta
        self.data={'records':{},'halted':False};self.calls=0
    def save(self):pass
    def halt(self,reason):self.data.update(halted=True,stop_reason=reason)
    def preflight(self,prompt):
        if self.data['halted']:raise BudgetStop(self.data['stop_reason'])
    def dispatch(self,key,prompt,*,kind,on_sent):
        self.calls+=1;on_sent();self.data['records'][key]=account(self.delta)
        if self.unknown or self.delta==0:self.halt('unknown usage or possibly delayed account charge; manual investigation required')
        usage=None if self.unknown else {'input_tokens':2,'output_tokens':3}
        if self.failed:
            exc=ValueError('ordinary fixture failure');exc.usage=usage;raise exc
        return {'text':'fixture','usage':usage}


class AdapterTests(unittest.TestCase):
    def run_case(self,inner,rows):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        replies=iter([proof([]),proof(rows)])
        transport=InvoiceTransport(inner,Path(temporary.name),query=lambda:next(replies))
        return transport

    def test_success_cost_and_replay_protection(self):
        inner=FakeQuota();transport=self.run_case(inner,[invoice()])
        result=transport.dispatch('one','prompt')
        self.assertEqual(result['metadata']['actual_platform_units'],7)
        with self.assertRaises(BudgetStop):transport.dispatch('one','prompt')
        self.assertEqual(inner.calls,1)

    def test_certified_failure_continues_unknown_wire_usage_stays_unknown(self):
        inner=FakeQuota(failed=True,unknown=True);transport=self.run_case(inner,[invoice()])
        with self.assertRaises(ValueError) as raised:transport.dispatch('one','prompt')
        self.assertIsNone(raised.exception.usage);self.assertFalse(inner.data['halted'])
        self.assertTrue(raised.exception.metadata['billing_certified']);transport.preflight('next')
        self.assertTrue(inner.data['invoice_reconciliations'][0]['wire_usage_still_unknown'])

    def test_unmatched_failure_keeps_halt(self):
        inner=FakeQuota(failed=True,unknown=True);transport=self.run_case(inner,[])
        with self.assertRaises(ValueError):transport.dispatch('one','prompt')
        with self.assertRaises(BudgetStop):transport.preflight('next')
        self.assertTrue(inner.data['halted'])

    def test_other_halt_not_overridden_by_invoice(self):
        inner=FakeQuota(failed=True,unknown=True)
        original=inner.dispatch
        def dispatch(*a,**k):
            try:return original(*a,**k)
            finally:inner.halt('observed account debit exceeded reservation/ceiling')
        inner.dispatch=dispatch;transport=self.run_case(inner,[invoice()])
        with self.assertRaises(ValueError):transport.dispatch('one','prompt')
        self.assertTrue(inner.data['halted'])

    def test_successful_unknown_response_usage_not_certified(self):
        inner=FakeQuota(unknown=True);transport=self.run_case(inner,[invoice()])
        with self.assertRaises(BudgetStop) as raised:transport.dispatch('one','prompt')
        self.assertIsNone(raised.exception.usage);self.assertTrue(inner.data['halted'])

    def test_explicit_zero_invoice_known_wire_tokens_can_continue(self):
        inner=FakeQuota(delta=0);transport=self.run_case(inner,[invoice(0)])
        self.assertEqual(transport.dispatch('one','prompt')['metadata']['actual_platform_units'],0)
        self.assertFalse(inner.data['halted'])


if __name__=='__main__':unittest.main()
