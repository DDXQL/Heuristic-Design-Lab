"""Local fixtures only; no paid API and no real benchmark holdouts."""
from copy import deepcopy
from dataclasses import replace
import hashlib,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_development_continuation import fixture,reduce_fixture
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real import development_acceptance as dev
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.continuation import source_evidence,check_dispatch_gate
from fjsp_usage.research_real.workflow import Workflow
from fjsp_usage.research_real.quota_guard import QuotaGuardedTransport
from fjsp_usage.research_real.staged_evaluation import create_synthetic_dataset,StagedDataset


def setup(tmp):
    root=Path(tmp)
    manifest=create_synthetic_dataset(root/'fixtures',count=2)
    body=json.loads(manifest.read_text());body['synthetic']=False;atomic_json(manifest,body)
    dataset=StagedDataset(manifest,project_root=manifest.parent,mode='real')
    original,source,_=fixture(tmp,five_unique=True,dataset_override=dataset)
    reduced=reduce_fixture(original)
    evidence=source_evidence(reduced)
    plan={'version':'single-P-seen-train-v1','arm':'P','max_new_requests':10,
        'retained_unknown_requests':{k:12000000 for k in evidence['unresolved']},
        'validation_names':[dataset.names['train'][0]],'test_names':[dataset.names['train'][1]],
        'previous_batches':{},'billing_evidence':{},'authorization':'Independent local handwritten test only.'}
    config=replace(reduced.config,real_requests_authorized=True,development_acceptance=plan)
    flow=Workflow(root/'runs/single',config=config,dataset=dataset,project_root=root)
    flow.prepare_continuation()
    return flow,source,evidence


class Handwritten:
    redact=staticmethod(lambda x:x)
    def __init__(self,flow,usage=True):
        self.config=flow.config;self.identity=digest({'provider':flow.config.payload()['provider'],'mode':'real'})
        self.calls=[];self.usage=usage
    def preflight(self,prompt):pass
    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        self.calls.append(key);on_sent()
        from fjsp_usage.research.candidates import U_ARGS
        code='def select_heuristic('+', '.join(U_ARGS)+'):\n    return 0\n'
        return {'text':'{Handwritten fixture duplicate.}\n```python\n'+code+'```',
                'usage':{'input_tokens':5,'output_tokens':5} if self.usage else None}


def quota(used):
    return {'quota':{'available':True,'total_granted':100000000,'total_used':used,
            'total_available':100000000-used,'unlimited_quota':False,'expires_at':0}}


class SinglePTests(unittest.TestCase):
    def test_retained_unknown_exact_binding_only_P_and_ten_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            f,s,e=setup(tmp);before=deepcopy(f.ledger.data['records'])
            check_dispatch_gate(f)
            for phase in ('H/init','r101/init','r101/B0'):
                with self.assertRaises(BudgetStop):f.ledger.reserve('different',phase,'prompt')
            for i in range(10):f.ledger.reserve(f'r101/P/P/g0000/{i:06d}','r101/P',str(i))
            with self.assertRaises(BudgetStop):f.ledger.reserve('r101/P/P/g0000/000010','r101/P','11')
            self.assertTrue(all(f.ledger.data['records'][k]==v for k,v in before.items()))
            f.ledger.data['continuation_unresolved_requests']=[]
            with self.assertRaises(ValueError):check_dispatch_gate(f)
            self.assertEqual(json.loads((s/'budget.json').read_text())['records'],before)

    def test_quota_retains_hold_checks_each_request_and_no_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            f,_,e=setup(tmp);t=Handwritten(f);values=iter((quota(1284585),quota(1284595)))
            retained={k:e['quota']['records'][k] for k in e['unresolved']}
            g=QuotaGuardedTransport(t,f.directory/'platform_quota.json',f.context,
                query=lambda:next(values),clock=lambda:0,sleep=lambda _:None,
                retained_records=retained,allowed_phase='r101/P/')
            g.dispatch('r101/P/P/g0000/000000','prompt')
            self.assertTrue(all(g.data['records'][k]==v for k,v in retained.items()))
            with self.assertRaises(BudgetStop):g.dispatch(next(iter(retained)),'same')
            with self.assertRaises(BudgetStop):g.dispatch('r101/B0/one','other')
            g.data['records'].pop(next(iter(retained)))
            with self.assertRaises(BudgetStop):g.preflight('new')
            self.assertEqual(len(t.calls),1)

    def test_quota_insufficient_with_all_holds_blocks_and_new_unknown_still_halts(self):
        with tempfile.TemporaryDirectory() as tmp:
            f,_,e=setup(tmp);t=Handwritten(f)
            g=QuotaGuardedTransport(t,f.directory/'platform_quota.json',f.context,
                query=lambda:quota(7000000),retained_records={k:e['quota']['records'][k] for k in e['unresolved']},allowed_phase='r101/P/')
            with self.assertRaises(BudgetStop):g.preflight('new')
            self.assertFalse(t.calls)
        with tempfile.TemporaryDirectory() as tmp:
            f,_,e=setup(tmp);t=Handwritten(f,usage=False);values=iter((quota(1000),quota(1010)))
            g=QuotaGuardedTransport(t,f.directory/'platform_quota.json',f.context,
                query=lambda:next(values),clock=lambda:0,sleep=lambda _:None,
                retained_records={k:e['quota']['records'][k] for k in e['unresolved']},allowed_phase='r101/P/')
            g.dispatch('r101/P/P/g0000/000000','prompt')
            self.assertTrue(g.data['halted'])
            with self.assertRaises(BudgetStop):g.preflight('new')

    def test_complete_generation_even_all_duplicates_and_seen_train_selection_freeze_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            f,s,e=setup(tmp);original={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in s.glob('*.json')}
            transport=Handwritten(f);f._client=transport
            f.train_eval=lambda *args: (_ for _ in ()).throw(AssertionError('duplicate must not be evaluated'))
            result=f.search_arm(101,'P');self.assertEqual(result['status'],'completed')
            self.assertEqual(len(transport.calls),10)
            for arm in ('B0','B1','B2'):
                with self.assertRaises(ValueError):f.search_arm(101,arm)
            with patch('fjsp_usage.research_real.workflow.JsonCandidateTransport',side_effect=AssertionError('no provider after search')):
                selected=dev.selection(f); frozen=dev.freeze(f)
                tested=dev.test(f);report=dev.report(f)
            self.assertEqual(report['candidate_outcomes'],{'duplicate':10})
            self.assertEqual(report['initial_ids'],report['final_ids'])
            self.assertEqual(report['actual_new_requests'],10);self.assertTrue(tested['result']['valid'])
            self.assertEqual(frozen,dev.freeze(f))
            self.assertEqual(frozen['selected_row']['id'],tested['selected_id'])
            self.assertTrue(all(stage.startswith('development_') for stage,_ in f.dataset.opened))
            self.assertFalse((f.directory/'Search_complete.json').exists())
            self.assertEqual(original,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in s.glob('*.json')})

    def test_evidence_bound_resume_preserves_two_calls_child_and_unknown_tokens(self):
        from fjsp_usage.research_real.continuation import declaration
        from fjsp_usage.research_real.real_transport import TransportError
        from fjsp_usage.research.candidates import U_ARGS
        import math
        with tempfile.TemporaryDirectory() as tmp:
            f,_,e=setup(tmp)
            class FailSecond(Handwritten):
                def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
                    self.calls.append(key);on_sent()
                    if len(self.calls)==2: raise TransportError('Independent fixture timeout; no response')
                    code='def select_heuristic('+', '.join(U_ARGS)+'):\n    return 0 if progress < 0.17 else 1\n'
                    return {'text':'{Handwritten.}\n```python\n'+code+'```','usage':{'input_tokens':5,'output_tokens':5},
                            'metadata':{'model':self.config.provider.expected_response_model}}
            t=FailSecond(f);values=iter((quota(1000),quota(1010),quota(1010)))
            f._client=QuotaGuardedTransport(t,f.directory/'platform_quota.json',f.context,
                query=lambda:next(values),clock=lambda:0,sleep=lambda _:None,
                retained_records={k:e['quota']['records'][k] for k in e['unresolved']},allowed_phase='r101/P/')
            names=f.dataset.names['train']
            f.train_eval=lambda *args:{'valid':True,'fitness':-1.,'total_instances':len(names),
                'instances':[{'file':name,'makespan':10,'lower_bound':10,'score':-1.} for name in names]}
            self.assertEqual(f.search_arm(101,'P')['status'],'budget_stopped')
            state=json.loads((f.directory/'r101/P/checkpoint.json').read_text())
            self.assertEqual(len(state['attempts']),2);self.assertEqual(len(state['children']),1)
            sourcequota=json.loads((f.directory/'platform_quota.json').read_text())
            failed='r101/P/P/g0000/000001';q=sourcequota['records'][failed]
            proof=f.directory/'failure_invoice.json'
            atomic_json(proof,{'success':True,'inference_requests':0,'records':[{
                'request_id':'local-invoice','type':2,'quota':7,'model_name':f.config.provider.model,
                'created_at':math.ceil(q['finished_at']),'prompt_tokens':5,'completion_tokens':0}]})
            oldbudget=json.loads((f.directory/'budget.json').read_text())
            oldpins=declaration(f.directory)
            plan={**f.config.development_acceptance,'search_resume_source':oldpins,
                'settled_failed_requests':{failed:{'path':str(proof.relative_to(f.project_root)),
                    'sha256':hashlib.sha256(proof.read_bytes()).hexdigest(),'provider_request_id':'local-invoice'}}}
            new=Workflow(f.directory.parent/'continued',config=replace(f.config,development_acceptance=plan),
                dataset=f.dataset,project_root=f.project_root)
            new.prepare_continuation();check_dispatch_gate(new)
            resumed=json.loads((new.directory/'r101/P/checkpoint.json').read_text())
            self.assertEqual(len(resumed['attempts']),2);self.assertEqual(resumed['cursor'],2)
            self.assertEqual(resumed['children'][0]['receipt']['ledger_identity'],f.ledger.identity)
            self.assertEqual(new.ledger.data['records'],oldbudget['records'])
            self.assertIsNone(new.ledger.data['records'][failed]['usage'])
            self.assertEqual(dev.check_plan(new,source_evidence(new))['settlement_min_used'],1017)
            new._client=Handwritten(new)
            self.assertEqual(new.search_arm(101,'P')['status'],'completed')
            self.assertEqual(len(new._client.calls),8)
            self.assertTrue(all(not key.endswith('000000') and not key.endswith('000001') for key in new._client.calls))
            selected=dev.selection(new);dev.freeze(new);dev.test(new)
            self.assertEqual(oldpins,declaration(f.directory))
            self.assertEqual(len(new.ledger.data['records']),len(oldbudget['records'])+8)

    def test_holdout_names_or_missing_retained_reservations_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f,_,e=setup(tmp)
            for update in ({'validation_names':['validation_0.fjsp']},{'retained_unknown_requests':{}}):
                plan={**f.config.development_acceptance,**update}
                f.config=replace(f.config,development_acceptance=plan)
                with self.assertRaises(ValueError):dev.check_plan(f,e)

if __name__=='__main__':unittest.main()
