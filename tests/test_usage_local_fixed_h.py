"""Fictitious-real provenance and tiny temporary data. No real LLM or benchmark.

H assets below are handwritten UNIT fixtures, not generated or human-approved
research assets. Every transport dispatch is mocked and restricted to kind U.
"""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import H_ARGS, U_ARGS, validate_code
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal, make_receipt, review_member
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig, fingerprint, protocol
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, TransportError
from fjsp_usage.research_real.staged_evaluation import create_synthetic_dataset, StagedDataset
from fjsp_usage.research_real.workflow import Workflow
from fjsp_usage.usage_v2.config import UsageConfig, LOCAL_REQUEST_EXPERIMENT
from fjsp_usage.usage_v2.fixed_h import VERSION, CORE_FILES, source_h
from fjsp_usage.usage_v2.workflow import UsageWorkflow
from experiments.tier2.usage_v2 import run
from test_local_request_budget import sha

ROOT=Path(__file__).resolve().parents[1]


class FixedHLocalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();(self.root/'requirements.txt').write_text('# unit fixture\n')
        # Source fingerprint checks use actual core code bytes, never a bypass.
        for name in CORE_FILES:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
        manifest=create_synthetic_dataset(self.root/'data',count=1)
        body=json.loads(manifest.read_text());body['synthetic']=False;atomic_json(manifest,body)
        self.dataset=StagedDataset(manifest,project_root=manifest.parent,mode='real')
        self.provider=ProviderConfig('https://leafapi.cc/v1/chat/completions','HANDWRITTEN-UNIT-MOCK',
            protocol='openai-chat-v1',api_key_env='FJSP_UNIT_KEY')
        self.source=self.root/'runs/frozen-H-unit-source';self.source.mkdir(parents=True)
        old=ExperimentConfig(provider=self.provider,mode='real',H_size=3,H_initialization_cap=3,
            population_size=5,cross_parents=5,instance_timeout=15,review_timeout=3)
        p=protocol(old,self.dataset.metadata,fingerprint(self.root));context=digest(p)
        atomic_json(self.source/'protocol.json',p)
        ledger={'identity':digest({'config':old.payload(),'context':context}),'mode':'real','records':{},'halted':False}
        journal={'requests':{}};rows=[]
        result={'valid':True,'total_instances':1,'fitness':-1.,'instances':[
            {'file':self.dataset.names['train'][0],'makespan':4,'lower_bound':4,'score':-1.,'feasible':True}]}
        for i,expression in enumerate(('-processing_time','-earliest_finish','remaining_work-processing_time')):
            c=validate_code('def priority('+', '.join(H_ARGS)+'):\n    return '+expression+'\n',
                kind='h',description='HANDWRITTEN UNIT FIXTURE ONLY')
            identifier=f'H/init/{i:06d}';key='H/init/'+identifier;usage={'input_tokens':1,'output_tokens':1}
            prompt='HANDWRITTEN HISTORICAL UNIT RECORD; not a generation call'
            record={'status':'completed','global_key':key,'usage':usage,'prompt':prompt,
                'prompt_key':digest({'prompt':prompt,'kind':'h'}),'text':'{HANDWRITTEN UNIT FIXTURE}\n```python\n'+c.code+'```'}
            ledger['records'][key]={'phase':'H/init','prompt_key':record['prompt_key'],'send_confirmed':True,
                'status':'completed','usage':usage,'reservation':usage}
            journal['requests'][identifier]=record
            receipt=make_receipt(c,record,SimpleNamespace(identity=ledger['identity'],data=ledger),old,
                digest({'provider':old.payload()['provider'],'mode':'real'}))
            rows.append({'id':identifier,'candidate':asdict(c),'fitness':-1.,'scores':[-1.],
                'training_result':result,'receipt':receipt})
        generated=seal({'kind':'H_candidates','mode':'real','context':context,'population':rows})
        members=[]
        for i,row in enumerate(rows):
            c=validate_code(row['candidate']['code'],description=row['candidate']['description'],kind='h')
            review=review_member(c,description='UNIT: '+str(i),reviewer='FICTITIOUS UNIT REVIEWER',
                method='handwritten-unit-review',note='Not a real technical review or research approval.')
            members.append({**row,'member_id':i,'review':review})
        self.H=seal({'kind':'H_frozen','mode':'real','context':context,'members':members,'member_count':3,
            'training_files':list(self.dataset.names['train']),'source_hash':generated['artifact_sha256']})
        atomic_json(self.source/'H_frozen.json',self.H);atomic_json(self.source/'H_candidates.json',generated)
        atomic_json(self.source/'budget.json',ledger)
        atomic_json(self.source/'H/budgeted_initial_requests.json',journal)
        atomic_json(self.source/'checkpoint.json',{'unit_old_cursor':123})
        atomic_json(self.source/'platform_quota.json',{'halted':True,'unknown_old_fee':'retained unchanged'})
        # An authoritative old count binding includes the native H ledger once.
        history=self.root/'runs/budget-predecessor';history.mkdir()
        binding=seal({'kind':'Fair_history_binding','mode':'real','lifetime_request_cap':300,
            'historical_request_slots':3,'historical_confirmed_sends':3,
            'real_budget_inventory':{ledger['identity']:sha(self.source/'budget.json')},'retained_account_hold':24000000})
        hp={'config':{'conditional_research':{'history_binding':binding}}};atomic_json(history/'protocol.json',hp)
        atomic_json(history/'budget.json',{'identity':digest({'config':hp['config'],'context':digest(hp)}),
            'mode':'real','halted':True,'records':{'old/unknown':{'status':'failed','send_confirmed':True,
                'usage':None,'reservation':{'input_tokens':65536,'output_tokens':32768}}}})
        pins={name:sha(self.source/name) for name in ('protocol.json','H_frozen.json','H_candidates.json',
            'budget.json','H/budgeted_initial_requests.json')}
        self.config=UsageConfig(provider=self.provider,mode='real',real_requests_authorized=True,H_size=3,
            H_initialization_cap=3,population_size=5,cross_parents=5,seeds=(301,),initialization_cap=20,
            generations=1,attempts_per_generation=10,total_request_cap=40,instance_timeout=15,
            usage_experiment_version=LOCAL_REQUEST_EXPERIMENT,
            request_budget={'version':'local-request-budget-v1','lifetime_request_cap':300,'history_source':{
                'directory':str(history),'protocol_sha256':sha(history/'protocol.json'),'budget_sha256':sha(history/'budget.json')}},
            fixed_h_source={'version':VERSION,'directory':str(self.source),'files_sha256':pins})
        self.directory=self.root/'runs/new-local-unit-run'
        self.config_path=self.root/'new-config.json';atomic_json(self.config_path,self.config.payload())
        self.before={str(p.relative_to(self.source)):(p.read_bytes(),p.stat().st_mtime_ns)
            for p in self.source.rglob('*') if p.is_file()}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name in ('socket.socket.connect','fjsp_usage.research_real.conditional_research.history_summary',
                'fjsp_usage.research_real.quota_guard.QuotaGuardedTransport.__init__',
                'fjsp_usage.usage_v2.billing.InvoiceTransport.__init__','fjsp_usage.usage_v2.billing.query_invoices',
                'fjsp_usage.usage_v2.model_migration.check_live_tariff'):
            self.stack.enter_context(patch(name,side_effect=AssertionError('NO REAL NETWORK / LEGACY FINANCE')))
        self.stack.enter_context(patch('fjsp_usage.usage_v2.registration.worktree_roots',return_value=[self.root]))
        self.stack.enter_context(patch.dict('os.environ',{'FJSP_UNIT_KEY':'not-a-real-key'}))
        self.calls=[]
        test=self
        def dispatch(inner,key,prompt,*,kind,on_sent):
            test.assertEqual(kind,'U','H must never be generated')
            test.calls.append((key,prompt));on_sent();n=len(test.calls)
            if key.endswith('A/g0000/000003'):raise TransportError('UNIT mock timeout; do not retry')
            vector=f'(1 + progress * {n}, 1, 0)' if '/B/' in key else f'(progress * {n}, 1, -1)'
            code='def use_heuristics('+', '.join(U_ARGS)+'):\n    return ('+('1' if '/B/' in key else '0')+', '+vector+')\n'
            return {'text':'{HANDWRITTEN U MOCK, NOT MODEL EVIDENCE}\n```python\n'+code+'```',
                'usage':None if n==1 else {'input_tokens':2,'output_tokens':3}}
        self.stack.enter_context(patch.object(JsonCandidateTransport,'dispatch',dispatch))

    def flow(self):
        return UsageWorkflow(self.directory,config=self.config,dataset=self.dataset,project_root=self.root)

    def cli(self,stage):
        with patch.object(run,'ROOT',self.root),patch.object(run,'StagedDataset',return_value=self.dataset),\
                patch('sys.argv',['run.py',stage,'--run-dir',str(self.directory),'--config',str(self.config_path)]),\
                redirect_stdout(io.StringIO()):run.main()

    def test_cli_full_pipeline_resumes_same_checkpoint_without_H_or_financial_calls(self):
        self.cli('local-preflight');self.cli('bind-h')
        flow=self.flow();bound,members=flow.h_asset()
        self.assertEqual(bound['members'],self.H['members'])
        self.assertEqual(bound['source_hash'],self.H['artifact_sha256'])
        self.assertNotEqual(bound['context'],self.H['context'])
        self.cli('initialize')
        flow=self.flow();initial=flow.read('r301/Shared_initial.json','Shared_initial')
        engine=flow.search_engine('r301/A','A',members,self.config.u_search(301),'r301/init','r301/A',initial=initial['population'])
        engine.run(stop_after_attempts=4)
        checkpoint=json.loads((self.directory/'r301/A/checkpoint.json').read_text())
        self.assertEqual(len(checkpoint['attempts']),4)
        self.cli('search');self.cli('report')
        self.assertEqual(len(self.calls),25)
        self.assertEqual(len({k for k,p in self.calls}),25)
        self.cli('search');self.cli('report');self.assertEqual(len(self.calls),25)
        report=self.flow().read('Usage_training_report.json','Usage_training_report')
        self.assertTrue(all(e['status']=='completed' for e in report['entries']))
        self.assertEqual(report['budget']['request_slots'],25)
        self.assertEqual(report['budget']['lifetime_request_slots'],29)
        self.assertIsNone(report['budget']['actual_cost'])
        self.assertEqual(report['historical_budget']['historical_request_slots'],4)
        self.assertEqual(len(report['fixed_member_training']),3)
        self.assertTrue(all(r['reused'] for r in report['fixed_member_training']))
        self.assertEqual(report['entries'][0]['usage']['MIX_steps'],0)
        self.assertGreater(report['entries'][1]['usage']['dual_steps'],0)
        self.assertTrue(all(split=='train' for split,name in self.dataset.opened))
        self.assertFalse((self.directory/'platform_quota.json').exists())
        self.assertFalse((self.directory/'billing').exists())
        self.assertEqual(self.before,{str(p.relative_to(self.source)):(p.read_bytes(),p.stat().st_mtime_ns)
            for p in self.source.rglob('*') if p.is_file()})

    def test_report_before_binding_and_missing_binding_fail_clearly(self):
        flow=self.flow()
        report=flow.training_report()
        self.assertEqual(report['fixed_member_training'],[])
        self.assertEqual(report['budget']['request_slots'],0)
        with self.assertRaisesRegex(ValueError,'bind-h'):flow.initialize_u(301)
        self.assertEqual(self.calls,[])

    def test_mode_data_runtime_and_legacy_payload_are_not_relaxed(self):
        implementation=fingerprint(self.root)
        changed=deepcopy(implementation);changed['files'][CORE_FILES[0]]='0'*64
        with self.assertRaisesRegex(ValueError,'runtime differs'):
            source_h(self.config,self.dataset,changed)
        data=SimpleNamespace(metadata={'different':'data'},names=self.dataset.names)
        with self.assertRaisesRegex(ValueError,'evaluation contract differs'):
            source_h(self.config,data,implementation)
        fake=replace(self.config,mode='synthetic',provider=ProviderConfig('http://localhost:9','MOCK'))
        with self.assertRaisesRegex(ValueError,'promoted'):
            source_h(fake,self.dataset,implementation)
        unbound=replace(self.config,fixed_h_source=None)
        self.assertNotIn('fixed_h_source',unbound.payload())
        self.assertEqual(UsageConfig.from_dict(unbound.payload()),unbound)

    def test_hash_order_review_receipt_result_and_source_pins_are_enforced(self):
        cases=('hash','order','review','receipt','incomplete','journal','missing_pin')
        for case in cases:
            with self.subTest(case=case):
                for name,(raw,mtime) in self.before.items():(self.source/name).write_bytes(raw)
                cfg=deepcopy(self.config.fixed_h_source)
                h=deepcopy(self.H)
                if case=='hash':(self.source/'H_frozen.json').write_text('{}')
                elif case=='journal':
                    p=self.source/'H/budgeted_initial_requests.json';j=json.loads(p.read_text())
                    next(iter(j['requests'].values()))['text']='wrong original response';atomic_json(p,j)
                    cfg['files_sha256']['H/budgeted_initial_requests.json']=sha(p)
                elif case=='missing_pin':cfg['files_sha256'].pop('H/budgeted_initial_requests.json')
                else:
                    if case=='order':h['members'][0]['member_id']=2
                    if case=='review':h['members'][0]['review']['reviewed_code_key']='wrong'
                    if case=='receipt':h['members'][0]['receipt']['ledger_identity']='wrong'
                    if case=='incomplete':h['members'][0]['training_result']['valid']=False
                    h.pop('artifact_sha256');atomic_json(self.source/'H_frozen.json',seal(h))
                    cfg['files_sha256']['H_frozen.json']=sha(self.source/'H_frozen.json')
                with self.assertRaises(ValueError):
                    source_h(replace(self.config,fixed_h_source=cfg),self.dataset,fingerprint(self.root))
        self.assertEqual(self.calls,[])

    def test_rebound_H_is_rechecked_and_cannot_be_changed_or_self_referenced(self):
        flow=self.flow();flow.bind_fixed_h()
        path=self.directory/'H_frozen.json';bound=json.loads(path.read_text())
        inherited={'version':VERSION,'directory':str(self.directory),'files_sha256':{
            n:sha(self.directory/n) for n in ('protocol.json','H_frozen.json')}}
        again,members=source_h(replace(self.config,fixed_h_source=inherited),self.dataset,fingerprint(self.root),
            target=self.root/'runs/another-independent-run')
        self.assertEqual(again['members'],self.H['members']);self.assertEqual(len(members),3)
        bound['members'].reverse();bound.pop('artifact_sha256');atomic_json(path,seal(bound))
        with self.assertRaisesRegex(ValueError,'changed'):flow.h_asset()
        cfg=deepcopy(self.config.fixed_h_source);cfg['directory']=str(self.directory)
        with self.assertRaisesRegex(ValueError,'self-reference'):
            source_h(replace(self.config,fixed_h_source=cfg),self.dataset,fingerprint(self.root),target=self.directory)
        self.assertEqual(self.calls,[])

    def test_existing_conditional_H_uses_original_scope_and_receipt_auditor(self):
        from test_conditional_research import setup
        # A separate pre-existing conditional UNIT fixture, with no H model
        # dispatch or H scheduling. Its old scores are handwritten references.
        root=self.root/'conditional-unit';root.mkdir()
        for name in CORE_FILES:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
        pending,_,_=setup(root)
        oldH=json.loads((root/'runs/target/H_frozen.json').read_text())
        d=deepcopy(pending.config.conditional_research)
        d['scope_approval']={'reviewer':'FICTITIOUS UNIT REVIEWER','scope':'conditional-fixed-H-research',
            'note':'Handwritten unit fixture only, not a real approval.',
            'source_H_sha256':oldH['artifact_sha256'],'member_code_keys':[r['candidate']['key'] for r in oldH['members']]}
        original=Workflow(root/'runs/conditional-frozen-unit',config=replace(pending.config,conditional_research=d),
            dataset=pending.dataset,project_root=root)
        rows=[{'source_row':r,'result':r['training_result']} for r in oldH['members']]
        a=original.write('Conditional_H_reassessment.json','Conditional_H_reassessment',
            source_H_hash=oldH['artifact_sha256'],rows=rows,training_files=list(pending.dataset.names['train']))
        H=original.write('H_frozen.json','H_frozen',member_count=2,training_files=list(pending.dataset.names['train']),
            source_hash=a['artifact_sha256'],scope_approval=d['scope_approval'],
            members=[{**r,'conditional_source_hash':a['artifact_sha256']} for r in oldH['members']])
        source={'version':VERSION,'directory':str(original.directory), 'files_sha256':{
            name:sha(original.directory/name) for name in ('protocol.json','H_frozen.json','Conditional_H_reassessment.json')}}
        cfg=replace(self.config,H_size=2,instance_timeout=original.config.instance_timeout,
            review_timeout=original.config.review_timeout,fixed_h_source=source)
        actual,members=source_h(cfg,pending.dataset,fingerprint(root))
        self.assertEqual(actual,H);self.assertEqual(len(members),2)
        self.assertEqual([r['review'] for r in actual['members']],[r['review'] for r in oldH['members']])
        # Even correctly re-sealed/re-pinned files cannot replace missing
        # original research-scope approval with a new wrapper.
        p=deepcopy(original.protocol);p['config']['conditional_research']['scope_approval']=None
        ctx=digest(p);atomic_json(original.directory/'protocol.json',p)
        a.pop('artifact_sha256');a['context']=ctx;a=seal(a)
        atomic_json(original.directory/'Conditional_H_reassessment.json',a)
        H.pop('artifact_sha256');H['context']=ctx;H['source_hash']=a['artifact_sha256']
        for r in H['members']:r['conditional_source_hash']=a['artifact_sha256']
        atomic_json(original.directory/'H_frozen.json',seal(H))
        source['files_sha256']={n:sha(original.directory/n) for n in source['files_sha256']}
        with self.assertRaisesRegex(ValueError,'approval binding'):
            source_h(replace(cfg,fixed_h_source=source),pending.dataset,fingerprint(root))
        source['files_sha256'].pop('Conditional_H_reassessment.json')
        with self.assertRaisesRegex(ValueError,'reassessment'):
            source_h(replace(cfg,fixed_h_source=source),pending.dataset,fingerprint(root))
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
