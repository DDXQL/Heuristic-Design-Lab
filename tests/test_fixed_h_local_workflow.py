"""Staged CLI E2E: frozen HANDWRITTEN H, Mock LLM, real toy21 scheduler.

No benchmark holdout, real provider, account endpoint or invoice endpoint.
All fixture candidates/scores live in TemporaryDirectory and are not research evidence.
"""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'experiments/tier2/research_real_v1'))
import run as staged_cli
from fjsp_usage.research.candidates import H_ARGS, validate_code
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal, review_member
from fjsp_usage.research_real.budget import REQUEST_BUDGET_VERSION
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig, fingerprint, protocol
from fjsp_usage.research_real.fixed_h import VERSION, bind_h, source_bundle
from fjsp_usage.research_real.fixtures import fixture_response
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from fjsp_usage.research_real.staged_evaluation import StagedDataset, create_synthetic_dataset
from fjsp_usage.research_real.workflow import Workflow, ARMS


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FixedHLocalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name).resolve()
        (cls.root/'code').symlink_to(ROOT/'code', target_is_directory=True)
        (cls.root/'requirements.txt').symlink_to(ROOT/'requirements.txt')
        cls.manifest = create_synthetic_dataset(cls.root/'toy', count=21)
        cls.dataset = StagedDataset(cls.manifest, project_root=cls.manifest.parent, mode='synthetic')
        cls.original = ExperimentConfig(ProviderConfig('http://127.0.0.1:1/never-used',
            'HANDWRITTEN-MOCK-NOT-A-MODEL'), H_size=10,H_initialization_cap=10,H_attempts=10,
            population_size=5,cross_parents=5,initialization_cap=20,generations=1,
            attempts_per_generation=10,seeds=(201,),total_request_cap=60,
            instance_timeout=15,training_diagnostics=True)
        cls.source = cls.root/'runs'/'HANDWRITTEN-frozen-H'
        cls.source.mkdir(parents=True)
        p = protocol(cls.original, cls.dataset.metadata, fingerprint(cls.root))
        atomic_json(cls.source/'protocol.json',p)
        instances = cls.dataset.load('train')
        members = []
        for i in range(10):
            code = 'def priority('+', '.join(H_ARGS)+f'):\n    return -earliest_finish + {i/100} * processing_time\n'
            candidate = validate_code(code,kind='h',description='HANDWRITTEN synthetic H fixture')
            result = cls.dataset.evaluate(candidate,(), 'train',timeout=15,instances=instances)
            if not result['valid']: raise AssertionError(result)
            text = '{HANDWRITTEN synthetic H fixture.}\n```python\n'+code+'```'
            receipt = {'mode':'synthetic','model':cls.original.provider.model,'protocol':'json-candidate-v1',
                'transport_identity':'HANDWRITTEN','ledger_identity':'HANDWRITTEN-FIXTURE-NOT-A-REAL-SEND',
                'global_key':f'H/init/{i:06d}','prompt_key':'HANDWRITTEN','status':'completed',
                'send_confirmed':True,'response_text':text,'response_sha256':digest(text),'usage':None}
            review = review_member(candidate,description='HANDWRITTEN synthetic behavior fixture',
                reviewer='HANDWRITTEN FIXTURE, not DDXQL',method='synthetic-unit-test',note='toy only')
            members.append({'id':f'H/init/{i:06d}','member_id':i,'candidate':asdict(candidate),
                'training_result':result,'fitness':result['fitness'],'scores':[r['score'] for r in result['instances']],
                'receipt':receipt,'review':review})
        cls.H = seal({'kind':'H_frozen','mode':'synthetic','context':digest(p),
            'member_count':10,'members':members,'training_files':list(cls.dataset.names['train'])})
        atomic_json(cls.source/'H_frozen.json',cls.H)
        d = {'version':VERSION,'run':cls.source.name,'protocol_sha256':sha(cls.source/'protocol.json'),
             'H_frozen_sha256':sha(cls.source/'H_frozen.json')}
        cls.config = replace(cls.original,fixed_h_source=d,request_budget={
            'version':REQUEST_BUDGET_VERSION,'lifetime_request_cap':300,'history_source':None})

    def test_cli_frozen_H_to_shared_U_four_arms_and_report_with_real_toy21_evaluation(self):
        folder = self.root/'runs'/'NEW-MOCK-U-ONLY'
        config_path = self.root/'HANDWRITTEN.config.json'
        atomic_json(config_path,self.config.payload())
        before = {p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.source.iterdir()}
        calls, evaluated, opened = [], [], []
        original_evaluate, original_load = StagedDataset.evaluate, StagedDataset.load
        def dispatch(inner,key,prompt,*,kind,on_sent):
            self.assertEqual(kind,'U')
            calls.append((key,prompt)); on_sent()
            response = fixture_response({'kind':kind},len(calls))
            if len(calls)==1: response['usage']=None
            return response
        def evaluate(dataset,candidate,members,split,**kwargs):
            self.assertEqual(split,'train'); self.assertEqual(candidate.kind,'U')
            result = original_evaluate(dataset,candidate,members,split,**kwargs)
            self.assertTrue(result['valid']); self.assertEqual(len(result['instances']),21)
            self.assertTrue(all(r['feasible'] for r in result['instances']))
            evaluated.append(result)
            return result
        def load(dataset,split,**kwargs):
            self.assertEqual(split,'train'); opened.append(split)
            return original_load(dataset,split,**kwargs)
        def stage(name,*,resume=True,extras=()):
            args = ['run.py',name,'--run-dir',str(folder),'--config',str(config_path),
                    '--manifest',str(self.manifest),*extras]
            if resume: args.append('--resume')
            with patch.object(sys,'argv',args),redirect_stdout(io.StringIO()): staged_cli.main()
        with ExitStack() as stack:
            stack.enter_context(patch.object(staged_cli,'ROOT',self.root))
            stack.enter_context(patch.object(JsonCandidateTransport,'dispatch',dispatch))
            stack.enter_context(patch.object(StagedDataset,'evaluate',evaluate))
            stack.enter_context(patch.object(StagedDataset,'load',load))
            for target in ('socket.socket.connect','urllib.request.urlopen',
                    'fjsp_usage.research_real.quota_guard.QuotaGuardedTransport.__init__',
                    'fjsp_usage.research_real.single_billing.InvoiceTransport.__init__'):
                stack.enter_context(patch(target,side_effect=AssertionError('NO NETWORK/METADATA')))
            stage('bind-fixed-h',resume=False)
            stage('preflight')
            stage('bind-fixed-h')  # idempotent H binding, never H generation/review/solve
            self.assertEqual(calls,[]); self.assertEqual(evaluated,[])
            stage('initialize-u',extras=('--seed','201','--max-new-requests','2'))
            self.assertEqual(len(calls),2)
            stage('initialize-u',extras=('--seed','201'))
            self.assertEqual(len(calls),5)
            for arm in ARMS: stage('search-arm',extras=('--seed','201','--arm',arm))
            stage('search'); stage('training-report')
            self.assertEqual(len(calls),45)
            self.assertEqual(len(evaluated),45)
            # Completed resume must reuse responses, fitness and final populations.
            stage('initialize-u',extras=('--seed','201'))
            stage('search'); stage('training-report')
            self.assertEqual(len(calls),45); self.assertEqual(len(evaluated),45)
        h = json.loads((folder/'H_frozen.json').read_text())
        self.assertEqual(h['members'],self.H['members'])
        self.assertEqual(h['source_H_hash'],self.H['artifact_sha256'])
        self.assertNotEqual(h['context'],self.H['context'])
        self.assertEqual((h['new_H_requests'],h['new_H_evaluations'],h['new_technical_reviews']),(0,0,0))
        self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.source.iterdir()})
        report=json.loads((folder/'Training_report.json').read_text())
        self.assertEqual([e['phase'] for e in report['entries']],['completed']*4)
        self.assertEqual(report['budget']['request_slots'],45)
        self.assertEqual(report['budget']['unknown_usage_requests'],1)
        self.assertIsNone(report['budget']['actual_cost'])
        self.assertEqual(len(set(k for k,p in calls)),45)
        self.assertFalse((folder/'platform_quota.json').exists())
        self.assertFalse((folder/'billing').exists())
        initial=json.loads((folder/'r201/Shared_initial.json').read_text())
        for arm in ARMS:
            final=json.loads((folder/f'r201/{arm}/Final_population.json').read_text())
            self.assertEqual(final['shared_initial_hash'],initial['artifact_sha256'])
            checkpoint=json.loads((folder/f'r201/{arm}/checkpoint.json').read_text())
            expected=(['E1']*2+['E2']*2+['M1']*2+['M2']*2+['M3']*2
                      if arm in ('B0','B1') else ['CROSS']*5+['MUTATE']*5)
            self.assertEqual([a['operator'] for a in checkpoint['attempts']],expected)
        self.assertTrue(opened and set(opened)=={'train'})

    def test_source_gates_no_provider_H_rebuild_or_mode_promotion(self):
        H,members=source_bundle(self.root,self.config,self.dataset)
        self.assertEqual(len(members),10)
        self.assertEqual(H['members'],self.H['members'])
        self.assertNotIn('H/init',self.config.phase_caps())
        folder=self.root/'runs'/'MOCK-GATE-CHECK'
        with patch.object(Workflow,'client',side_effect=AssertionError('NO CLIENT')):
            flow=Workflow(folder,config=self.config,dataset=self.dataset,project_root=self.root)
            bind_h(flow)
            with self.assertRaises(ValueError): flow.generate_h()
            before=(self.source/'protocol.json').read_bytes()
            with self.assertRaises(ValueError):
                Workflow(self.source,config=self.config,dataset=self.dataset,project_root=self.root)
            self.assertEqual(before,(self.source/'protocol.json').read_bytes())
        for c in (replace(self.config,instance_timeout=14),
                  replace(self.config,provider=replace(self.config.provider,max_output_tokens=2048))):
            with self.assertRaises(ValueError): source_bundle(self.root,c,self.dataset)
        with self.assertRaises(ValueError): replace(self.config,mode='real')
        altered=deepcopy(fingerprint(self.root))
        altered['files']['code/fjsp_usage/research/scheduler.py']='0'*64
        with patch('fjsp_usage.research_real.config.fingerprint',return_value=altered):
            with self.assertRaises(ValueError): source_bundle(self.root,self.config,self.dataset)
        pin=deepcopy(self.config.fixed_h_source);pin['H_frozen_sha256']='0'*64
        with self.assertRaises(ValueError): source_bundle(self.root,replace(self.config,fixed_h_source=pin),self.dataset)


if __name__=='__main__': unittest.main()
