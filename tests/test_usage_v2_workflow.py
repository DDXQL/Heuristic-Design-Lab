"""Two-arm source, budget, init failure and authentic synthetic provenance."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.research_real.staged_evaluation import StagedDataset,create_synthetic_dataset
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.fixtures import fixture_server
from fjsp_usage.research.candidates import H_ARGS,validate_code
from dataclasses import asdict
from fjsp_usage.usage_v2.config import UsageConfig
from fjsp_usage.usage_v2.workflow import UsageWorkflow
from fjsp_usage.usage_v2.fixtures import acceptance,response
from fjsp_usage.usage_v2.examples import write_examples
ROOT=Path(__file__).resolve().parents[1]

class PairedWorkflowTests(unittest.TestCase):
    def test_synthetic_full_paired_generation_same_P0_exact_slots_and_cost_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'acceptance';evidence=acceptance(directory,ROOT)
            self.assertEqual(evidence['new_real_requests'],0)
            self.assertEqual(evidence['fixture_dispatches'],26)
            report=json.loads((directory/'Usage_training_report.json').read_text())
            self.assertEqual(report['budget']['request_slots'],26)
            initial=report['initialization'][0]
            self.assertEqual(initial['categories']['code_duplicate'],1)
            self.assertEqual(len(initial['population']),5)
            a,b=report['entries']
            self.assertEqual(a['categories'],{'valid':8,'runtime_failure':1,'api_failure':1})
            self.assertEqual(b['categories'],{'valid':9,'parse_failure':1})
            self.assertEqual(a['usage']['MIX_steps'],0)
            self.assertGreater(b['usage']['dual_steps'],0)
            self.assertEqual([x['parents'] for x in a['attempts']],[x['parents'] for x in b['attempts']])
            self.assertGreater(b['cost']['combination_processing_seconds'],0)
            self.assertTrue(all(x['status']=='completed' for x in (a,b)))
            self.assertTrue(all(p=='train' for p,n in evidence['opened']))
            self.assertFalse((directory/'Test_complete.json').exists())
            self.assertEqual(set(json.loads((directory/'budget.json').read_text())['records'][k]['phase'] for k in json.loads((directory/'budget.json').read_text())['records']),{'r301/init','r301/A','r301/B'})

    def test_initialization_budget_exhausted_never_lower_N_or_start_arms(self):
        with tempfile.TemporaryDirectory() as tmp,fixture_server(responder=lambda payload,index:response(payload,1)) as (url,state):
            directory=Path(tmp)/'run';manifest=create_synthetic_dataset(Path(tmp)/'data',count=1)
            cfg=UsageConfig(provider=ProviderConfig(url,'HANDWRITTEN-LOCAL-FIXTURE'),mode='synthetic',H_size=3,
                H_initialization_cap=3,population_size=5,cross_parents=5,initialization_cap=5,
                generations=1,attempts_per_generation=10,seeds=(301,),total_request_cap=25,instance_timeout=10,training_diagnostics=True)
            ds=StagedDataset(manifest,project_root=manifest.parent,mode='synthetic')
            flow=UsageWorkflow(directory,config=cfg,dataset=ds,project_root=ROOT)
            h=validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -earliest_finish\n',kind='h')
            flow.write('Handwritten_H_fixture.json','Handwritten_H_fixture',members=[asdict(h)]*3)
            gate=flow.search_all()
            self.assertEqual(len(state['requests']),5)
            self.assertTrue(all(e['status']=='initialization_failed' for e in gate['entries']))
            self.assertFalse((directory/'r301/Shared_initial.json').exists())
            self.assertFalse((directory/'r301/A/checkpoint.json').exists())
            self.assertFalse((directory/'r301/B/checkpoint.json').exists())
            self.assertEqual(len(flow.ledger.data['records']),5)
            # Re-entry does not resend or refill.
            flow.search_all();self.assertEqual(len(state['requests']),5)

    def test_real_config_no_auth_no_scope_and_cumulative_unknowns_retained(self):
        from experiments.tier2.usage_v2.run import pending_config
        from fjsp_usage.research_real.conditional_research import history_summary,check_origin
        cfg=pending_config();self.assertFalse(cfg.real_requests_authorized)
        self.assertIsNone(cfg.conditional_research['scope_approval'])
        self.assertEqual(cfg.phase_caps(),{'r301/init':20,'r301/A':10,'r301/B':10})
        with self.assertRaises(ValueError):cfg.check_dispatch()
        history=history_summary(ROOT,cfg)
        self.assertEqual(history['historical_request_slots'],79)
        self.assertEqual(history['retained_account_hold'],12000000)
        pending=next(x for x in history['unknown_requests'] if x['key'].endswith('000034'))
        self.assertIsNone(pending['wire_usage']);self.assertEqual(pending['token_reservation'],{'input_tokens':65536,'output_tokens':32768})
        ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
        source,members,_=check_origin(ROOT,cfg,ds)
        self.assertEqual(len(members),10)
        self.assertEqual(ds.opened,[])
        with tempfile.TemporaryDirectory() as tmp:
            flow=UsageWorkflow(Path(tmp),config=cfg,dataset=ds,project_root=ROOT)
            with patch('fjsp_usage.research_real.workflow.JsonCandidateTransport',side_effect=AssertionError('must not read credentials')):
                with self.assertRaises(ValueError):flow.client()
            for stage in (flow.select,flow.test,flow.freeze):
                with self.assertRaises(ValueError):stage()
        for kwargs in ({'max_active_members':3},{'total_request_cap':41},{'population_size':4},{'phase_request_caps':{'r301/init':20,'r301/A':9,'r301/B':10}}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):replace(cfg,**kwargs)

    def test_context_changes_with_interface_H_weights_and_allowed_modes(self):
        from fjsp_usage.usage_v2.config import protocol
        from fjsp_usage.research.protocol import digest
        c=UsageConfig(provider=ProviderConfig('http://127.0.0.1:1234','TEST'),seeds=(301,),initialization_cap=5,population_size=5)
        p=protocol(c,{'manifest':'toy'},{'files':{}})
        self.assertEqual(p['arm_modes'],{'INIT':[0],'A':[0],'B':[0,1]})
        self.assertIn('tuple',p['language'])
        self.assertNotEqual(digest(p),digest({**p,'actions':'raw-unnormalized'}))

    def test_inspectable_examples_are_fixtures_and_match_first_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'examples';summary=write_examples(p)
            self.assertEqual(summary['first_actions'],{'fixed-h2':(1,0),'score-select':(0,0),'dual-mix':(0,1)})
            self.assertEqual(summary['complete_feasible_schedules'],3)
            self.assertIn('Handwritten',json.loads((p/'dual-mix.json').read_text())['notice'])

if __name__=='__main__':unittest.main()
