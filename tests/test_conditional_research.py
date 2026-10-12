"""Independent handcrafted provenance/quota fixtures, never real experiment assets."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_development_continuation import fixture
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.conditional_research import VERSION,prepare,history_summary,freeze_h,h_asset,check_origin
from fjsp_usage.research_real.staged_evaluation import create_synthetic_dataset,StagedDataset
from fjsp_usage.research_real.workflow import Workflow
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.training_report import write_training_report
from fjsp_usage.research_real.quota_guard import QuotaGuardedTransport


def setup(root):
    root=Path(root); manifest=create_synthetic_dataset(root/'tiny',count=1)
    # Local fictitious-real provenance exercises the same strict checks. These
    # hand-made toy data/receipts cannot match benchmark hashes or real journals.
    m=json.loads(manifest.read_text());m['synthetic']=False;atomic_json(manifest,m)
    ds=StagedDataset(manifest,project_root=manifest.parent,mode='real')
    original,source,H=fixture(root,dataset_override=ds)
    original.prepare_continuation()
    body={'success':True,'inference_requests':0,'records':[]}
    atomic_json(source/'billing.json',body)
    plan={'billing_evidence':{'path':'runs/source/billing.json',
          'sha256':hashlib.sha256((source/'billing.json').read_bytes()).hexdigest()}}
    old=replace(original.config,development_acceptance=None)
    # The audit only consumes this historical field; no executable dev config is
    # weakened to authorize a fictitious supplier.
    protocol=deepcopy(original.protocol); protocol['config']['development_acceptance']=plan
    from fjsp_usage.research.protocol import digest
    from fjsp_usage.research_real.assets import seal
    context=digest(protocol); atomic_json(original.directory/'protocol.json',protocol)
    for name in ('H_frozen.json','H_candidates.json'):
        a=json.loads((original.directory/name).read_text());a.pop('artifact_sha256');a['context']=context
        # Matching generated/frozen source hash is not used to promote this
        # wrapper: actual original code/review equality is separately checked.
        atomic_json(original.directory/name,seal(a))
    for name in ('budget.json','platform_quota.json'):
        b=json.loads((original.directory/name).read_text());b['identity']=digest({'config':protocol['config'],'context':context})
        atomic_json(original.directory/name,b)
    pins={str(p.relative_to(root/'runs')):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (root/'runs').rglob('*') if p.is_file()}
    declaration={'version':VERSION,'source_run':'target','source_files_sha256':pins,
        'history_batches':['target'],'lifetime_request_cap':300,'scope_approval':None,
        'baseline_policy':'validation_select_one_report_all_train','holdout_policy':'locked_until_protocol_and_search_complete'}
    config=replace(old,purpose='research',development_continuation_source=None,
        conditional_research=declaration,training_diagnostics=True,real_requests_authorized=False,
        population_size=2,cross_parents=2,initialization_cap=3,total_request_cap=43)
    return Workflow(root/'runs/research',config=config,dataset=ds,project_root=root),source,H


class ConditionalResearchTests(unittest.TestCase):
    def test_offline_reassesses_every_H_and_requires_actual_new_scope_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,source,H=setup(tmp); before={p:p.read_bytes() for p in source.rglob('*') if p.is_file()}
            with patch('fjsp_usage.research_real.workflow.JsonCandidateTransport',side_effect=AssertionError('no paid client')):
                asset=prepare(flow)
                self.assertEqual(len(asset['rows']),2)
                self.assertTrue(all(r['result']['valid'] for r in asset['rows']))
                self.assertEqual({s for s,n in flow.dataset.opened},{'train'})
                with self.assertRaisesRegex(ValueError,'actual conditional research scope approval'):freeze_h(flow)
                with self.assertRaises(ValueError):flow.client()
            self.assertFalse((flow.directory/'H_frozen.json').exists())
            self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
            self.assertEqual(flow.ledger.summary()['request_slots'],0)

    def test_history_preserves_unknown_tokens_slots_and_full_account_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,_,_=setup(tmp); report=history_summary(flow.project_root,flow.config)
            self.assertEqual(report['historical_request_slots'],6)
            self.assertEqual(report['historical_confirmed_sends'],6)
            self.assertEqual(report['retained_account_hold'],12000000)
            self.assertEqual(report['unknown_requests'][0]['wire_usage'],None)
            self.assertEqual(report['unknown_requests'][0]['token_reservation'],{'input_tokens':65536,'output_tokens':32768})
            before=report['historical_request_slots']
            flow.config=replace(flow.config,total_request_cap=300)
            with self.assertRaisesRegex(ValueError,'lifetime'):history_summary(flow.project_root,flow.config)

    def test_pin_changes_and_unknown_new_model_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,source,_=setup(tmp)
            flow.config=replace(flow.config,provider=replace(flow.config.provider,model='other'))
            with self.assertRaisesRegex(ValueError,'provider/model'):check_origin(flow.project_root,flow.config,flow.dataset)
            flow.config=replace(flow.config,provider=replace(flow.config.provider,model='gpt-5.6-sol'))
            path=source/'budget.json';path.write_text(path.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'historical research source changed'):prepare(flow)

    def test_explicit_scope_freeze_preserves_code_numbering_reviews_and_fresh_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending,source,H=setup(tmp)
            declaration=deepcopy(pending.config.conditional_research)
            sourceH=json.loads((pending.project_root/'runs/target/H_frozen.json').read_text())
            declaration['scope_approval']={'reviewer':'Local test fixture only','scope':'conditional-fixed-H-research',
                'note':'Explicit handwritten local fixture, not a real human research approval.',
                'source_H_sha256':sourceH['artifact_sha256'],'member_code_keys':[r['candidate']['key'] for r in H['members']]}
            flow=Workflow(pending.directory.parent/'approved-fixture',config=replace(pending.config,conditional_research=declaration),
                dataset=pending.dataset,project_root=pending.project_root)
            frozen=freeze_h(flow); loaded,members=h_asset(flow)
            self.assertEqual(len(members),2)
            for a,b in zip(frozen['members'],sourceH['members']):
                for k in ('member_id','review','candidate','receipt'): self.assertEqual(a[k],b[k])
                self.assertIn('single_solve_seconds',a['training_result']['instances'][0])
            self.assertNotEqual(frozen['context'],sourceH['context'])
            report=write_training_report(flow)
            self.assertTrue(all(r['phase']=='not_started' for r in report['entries']))
            self.assertEqual(report['budget']['request_slots'],0)
            self.assertEqual({s for s,n in flow.dataset.opened},{'train'})
            # Direct caller still cannot spend under a disabled authorization.
            with self.assertRaises(ValueError):flow.client()
            with self.assertRaises(ValueError):flow.generate_h()

    def test_wrong_code_scope_cannot_freeze_and_reassessment_never_imports_old_U(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending,_,_=setup(tmp)
            d=deepcopy(pending.config.conditional_research);sourceH=json.loads((pending.project_root/'runs/target/H_frozen.json').read_text())
            d['scope_approval']={'reviewer':'Fixture','scope':'conditional-fixed-H-research','note':'Fixture',
                'source_H_sha256':sourceH['artifact_sha256'],'member_code_keys':['wrong']}
            flow=Workflow(pending.directory.parent/'wrong',config=replace(pending.config,conditional_research=d),dataset=pending.dataset,project_root=pending.project_root)
            with self.assertRaisesRegex(ValueError,'exact original H'):freeze_h(flow)
            self.assertFalse((flow.directory/'r101/Shared_initial.json').exists())
            self.assertFalse((flow.directory/'H_frozen.json').exists())

    def test_conservative_retained_hold_and_new_failure_stop_remain_active(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            flow,_,_=setup(tmp)
            c=replace(flow.config,platform_quota_query_interval=.001)
            class T:
                config=c;identity='fixture';redact=staticmethod(str)
                def preflight(self,prompt): pass
                def dispatch(self,key,prompt,*,kind,on_sent):
                    on_sent();return {'text':'fixture','usage':None}
            def quota(used):
                return {'quota':{'available':True,'total_granted':100000000,'total_available':100000000-used,
                    'total_used':used,'unlimited_quota':False,'expires_at':0}}
            g=QuotaGuardedTransport(T(),Path(tmp)/'guard.json','c',query=lambda:quota(7000000),retained_extra=12000000)
            with self.assertRaisesRegex(BudgetStop,'insufficient'):g.preflight('p')
            g=QuotaGuardedTransport(T(),Path(tmp)/'guard2.json','c',query=lambda:quota(1500000),retained_extra=12000000)
            g.dispatch('r101/B0/x','p',kind='U')
            self.assertTrue(g.data['halted']);self.assertEqual(g.check_retained(),12000000)
            with self.assertRaises(BudgetStop):g.preflight('p')

if __name__=='__main__': unittest.main()
