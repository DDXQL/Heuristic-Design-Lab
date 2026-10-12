"""Independent handwritten evidence; no real provider or benchmark data."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import H_ARGS,U_ARGS,validate_code
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal,make_receipt,review_member
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig,fingerprint
from fjsp_usage.research_real.continuation import (declaration,source_evidence,
    check_dispatch_gate,check_binding,OLD_VERSION)
from fjsp_usage.research_real.continuation import search_snapshot
from fjsp_usage.research_real.leafapi import provider
from fjsp_usage.research_real.prompts import prompt_manifest
from fjsp_usage.research_real.search import V5BudgetedSearch
from fjsp_usage.research_real.workflow import Workflow


def fixture(root, *, interrupted=True, five_unique=False, dataset_override=None):
    root=Path(root); (root/'requirements.txt').write_text('')
    manifest=root/'manifest.json';manifest.write_text('{}')
    metadata={'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
    dataset=SimpleNamespace(metadata=metadata,names={'train':('tiny.fjs',)},path=manifest,
        verify=lambda *a,**k: None,
        load=lambda *a,**k: (_ for _ in ()).throw(AssertionError('no instance load')),
        evaluate=lambda *a,**k: (_ for _ in ()).throw(AssertionError('no evaluation')))
    if dataset_override is not None:
        dataset=dataset_override;metadata=dataset.metadata
    names=list(dataset.names['train'])
    config=ExperimentConfig(provider=provider(),mode='real',real_requests_authorized=True,
        purpose='framework_development',H_size=2,H_initialization_cap=3,
        H_generations=1,H_attempts=10,population_size=10 if five_unique else 4,cross_parents=5 if five_unique else 2,
        initialization_cap=12 if five_unique else 8,attempts_per_generation=10,generations=2 if five_unique else 1,seeds=(101,),
        total_request_cap=100,platform_quota_ceiling=30000000,
        platform_quota_reservation=12000000)
    pack=deepcopy(prompt_manifest());pack['version']=OLD_VERSION
    pack['sections'].pop('shared_initial_novelty');pack.pop('shared_initial_novelty')
    old={'mode':'real','config':config.payload(),'dataset':metadata,
         'prompt_pack':pack,'implementation':fingerprint(root)}
    context=digest(old); identity=digest({'config':config.payload(),'context':context})
    ledger={'identity':identity,'mode':'real','records':{},'halted':False}
    quota={'identity':identity,'records':{},'halted':False,'observed_used':100,
           'ceiling':30000000,'reservation':12000000}
    journals={phase:{'identity':'historical-fixture','requests':{}}
              for phase in ('H/init','H/search','r101/init')}
    result={'valid':True,'fitness':-1.,'total_instances':len(names),
            'instances':[{'file':name,'makespan':10,'lower_bound':10,'score':-1.} for name in names]}
    def candidate(kind,body):
        args=H_ARGS if kind=='h' else U_ARGS;name='priority' if kind=='h' else 'select_heuristic'
        return validate_code('def '+name+'('+', '.join(args)+'):\n    '+body+'\n',
                             description='Handwritten fixture.',kind=kind)
    def response(identifier,phase,c,*,pending=False):
        prompt='Independent handwritten fixture '+identifier
        prompt_key=digest({'prompt':prompt,'kind':c.kind});global_key=phase+'/'+identifier
        usage=None if pending else {'input_tokens':10,'output_tokens':20}
        record={'status':'pending' if pending else 'completed','prompt':prompt,
            'prompt_key':prompt_key,'global_key':global_key,'kind':c.kind,'usage':usage}
        if not pending:
            record.update(text='{Handwritten fixture.}\n```python\n'+c.code+'```',
                          response_metadata={'model':config.provider.expected_response_model})
        journals[phase]['requests'][identifier]=record
        ledger['records'][global_key]={'phase':phase,'prompt_key':prompt_key,
            'status':'reserved' if pending else 'completed','usage':usage,'send_confirmed':True,
            'reservation':{'input_tokens':65536,'output_tokens':32768}}
        quota['records'][global_key]={'status':'pending' if pending else 'settled',
            'send_confirmed':True,'before_used':100,'reserved':12000000}
        return record
    rows=[];H_evals={};H_checkpoint_rows=[];reviews={}
    for i,body in enumerate(('return -processing_time','return -earliest_finish')):
        c=candidate('h',body); identifier=f'H/init/{i:06d}'
        record=response(identifier,'H/init',c)
        base={'id':identifier,'candidate':asdict(c),'fitness':-1.,'scores':[-1.]*len(names)}
        H_checkpoint_rows.append(base);H_evals[identifier]={'status':'completed','result':result}
        receipt=make_receipt(c,record,SimpleNamespace(data=ledger,identity=identity),config,
                            digest({'provider':config.payload()['provider'],'mode':'real'}))
        rows.append({**base,'receipt':receipt,'training_result':result})
        reviews[c.key]={'description':body,'reviewer':'DDXQL','method':'human-fixture',
                        'note':'Independent local fixture, no scientific evidence.'}
    generated=seal({'kind':'H_candidates','mode':'real','context':context,'population':rows,
        'training_files':names,'member_count':2})
    H=seal({'kind':'H_frozen','mode':'real','context':context,'source_hash':generated['artifact_sha256'],
        'member_count':2,'training_files':names,'source_mechanism':'fixture',
        'members':[{**r,'member_id':i,'review':review_member(candidate('h',
            ('return -processing_time','return -earliest_finish')[i]),**reviews[r['candidate']['key']])}
            for i,r in enumerate(rows)]})
    population=[];evaluations={};attempts=[];seen={}
    bodies=['return 0','return int(0)','return 0 if progress < 0.5 else 1']
    if five_unique:
        bodies+=['return 0 if candidate_pair_ratio < 0.2 else 1',
                 'return 0 if remaining_work_mean < 0.3 else 1',
                 'return 0 if machine_ready_mean < 0.4 else 1']
    for i,body in enumerate(bodies):
        c=candidate('U',body);identifier=f'INIT/init/{i:06d}'
        response(identifier,'r101/init',c)
        population.append({'id':identifier,'candidate':asdict(c),'fitness':-1.,'scores':[-1.]*len(names)})
        evaluations[identifier]={'status':'completed','result':result};seen[c.key]=identifier
        attempts.append({'id':identifier,'operator':'I1','parents':[],'status':'valid'})
    pending_id=f'INIT/init/{len(bodies):06d}'
    c=candidate('U','return 0');response(pending_id,'r101/init',c,pending=interrupted)
    if not interrupted:
        attempts.append({'id':pending_id,'operator':'I1','parents':[],'status':'duplicate'})
    checkpoint={'signature':'historical-fixture','population':population,'children':[],
        'generation':0,'cursor':0,'init_cursor':len(bodies)+(not interrupted),'phase':'initialization',
        'inflight':{'id':pending_id,'operator':'I1','parents':[],'initial':True,
                     'prompt':'saved historical prompt'} if interrupted else None,
        'seen':seen,'evaluations':evaluations,'attempts':attempts,'rng':random.Random(101).getstate()}
    source=root/'runs/source';source.mkdir(parents=True)
    documents={'protocol.json':old,'budget.json':ledger,'platform_quota.json':quota,
        'H_candidates.json':generated,'H_frozen.json':H,'H_review_completed_20261010.json':reviews,
        'H/checkpoint.json':{'phase':'completed','generation':1,'population':H_checkpoint_rows,'evaluations':H_evals},
        'H/budgeted_initial_requests.json':journals['H/init'],
        'H/budgeted_evolution_requests.json':journals['H/search'],
        'r101/INIT/checkpoint.json':checkpoint,'r101/INIT/budgeted_initial_requests.json':journals['r101/init']}
    for name,value in documents.items():atomic_json(source/name,value)
    atomic_json(source/'human_review_confirmation_20261010.json',{
        'human_approved':True,'reviewer':'DDXQL','code_keys':list(reviews),
        'review_file_sha256':hashlib.sha256((source/'H_review_completed_20261010.json').read_bytes()).hexdigest(),
        'H_source_hash':generated['artifact_sha256']})
    new=replace(config,real_requests_authorized=False,development_continuation_source=declaration(source))
    flow=Workflow(root/'runs/target',config=new,dataset=dataset,project_root=root)
    return flow,source,H


def reduce_fixture(flow):
    old=flow.config
    caps=old.phase_caps()
    for arm in ('B0','B1','B2','P'):caps['r101/'+arm]=10
    N=5 if old.population_size==10 else 2
    new=replace(old,population_size=N,generations=1,attempts_per_generation=10,phase_request_caps=caps)
    pins=deepcopy(new.development_continuation_source)
    pins['search_change']={'from':search_snapshot(old),'to':search_snapshot(new),
        'shared_initial':'reuse_only','scope':'train_only','first_arm':'P','reason':'Explicit local reduced-development fixture.'}
    new=replace(new,development_continuation_source=pins)
    return Workflow(flow.directory.parent/'reduced',config=new,dataset=flow.dataset,project_root=flow.project_root)


class ContinuationTests(unittest.TestCase):
    def test_five_member_reuse_finishes_shared_initial_without_new_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            original,source,H=fixture(tmp,five_unique=True);flow=reduce_fixture(original)
            with patch('fjsp_usage.research_real.workflow.JsonCandidateTransport',side_effect=AssertionError('no client')):
                ready=flow.prepare_continuation()
                initialized=flow.initialize_u(101)
                self.assertEqual(initialized['status'],'initialized')
                self.assertEqual(len(initialized['asset']['population']),5)
                with self.assertRaises(BudgetStop):flow.search_arm(101,'P')
            self.assertTrue(ready['shared_initial_complete'])
            self.assertEqual(ready['initialization_cursor'],7)
            self.assertEqual(flow.config.cross_parents,5);self.assertEqual(flow.config.mutation_parents,1)
            self.assertEqual(flow.read('H_frozen.json','H_frozen')['members'],H['members'])
            for action in (flow.select,flow.freeze,flow.test,flow.search_all):
                with self.assertRaises(ValueError):action()
            with self.assertRaises(ValueError):flow.search_arm(101,'B0')
            self.assertFalse((flow.directory/'r101/P').exists())

    def test_explicit_reduction_cannot_change_scoring_budget_or_drop_U(self):
        with tempfile.TemporaryDirectory() as tmp:
            original,_,_=fixture(tmp,five_unique=True);flow=reduce_fixture(original)
            self.assertEqual(len(source_evidence(flow)['rows']),5)
            saved=flow.config
            for field,value in (('cross_parents',4),('instance_timeout',15),('total_request_cap',101)):
                flow.config=replace(saved,**{field:value})
                with self.assertRaises(ValueError):source_evidence(flow)
            flow.config=saved
            flow.config.development_continuation_source['search_change']['from']['population_size']=99
            with self.assertRaises(ValueError):source_evidence(flow)

    def test_mock_only_four_arms_reuse_one_population_and_existing_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            original,source,_=fixture(tmp,interrupted=False,five_unique=True);flow=reduce_fixture(original)
            flow.prepare_continuation()
            shared=flow.read('r101/Shared_initial.json','Shared_initial')
            initial_ids={r['id'] for r in shared['population']};calls=[];evaluations=[]
            class Handwritten:
                identity=digest({'provider':flow.config.payload()['provider'],'mode':'real'})
                def preflight(self,prompt):pass
                def redact(self,text):return text
                def dispatch(self,key,prompt,*,kind,on_sent):
                    calls.append(key);on_sent()
                    code='def select_heuristic('+', '.join(U_ARGS)+'):\n    return 0 if progress < '+str((len(calls)+1)/101)+' else 1\n'
                    return {'text':'{Handwritten local test only.}\n```python\n'+code+'```',
                        'usage':{'input_tokens':10,'output_tokens':20},'metadata':{'model':flow.config.provider.expected_response_model}}
            flow._client=Handwritten()  # Isolated fixture injection; never a provider/client for actual assets.
            def evaluate(c,m):
                evaluations.append(c.key)
                return {'valid':True,'fitness':-1.,'total_instances':1,
                    'instances':[{'file':'tiny.fjs','makespan':10,'lower_bound':10,'score':-1.}]}
            flow.train_eval=evaluate
            for arm in ('P','B0','B1','B2'):
                result=flow.search_arm(101,arm);self.assertEqual(result['status'],'completed')
                final=flow.read(f'r101/{arm}/Final_population.json','Final_population')
                self.assertEqual(final['shared_initial_hash'],shared['artifact_sha256'])
                self.assertEqual(len(final['population']),5)
                state=json.loads((flow.directory/f'r101/{arm}/checkpoint.json').read_text())
                self.assertEqual(state['generation'],1);self.assertEqual(len(state['attempts']),10)
                self.assertTrue(all(set(a['parents'])<=initial_ids for a in state['attempts']))
                for a in state['attempts']:
                    self.assertEqual(len(a['parents']),5 if a['operator'] in ('CROSS','E1','E2') else 1)
            self.assertEqual(len(calls),40);self.assertEqual(len(evaluations),40)
            self.assertEqual(flow.ledger.summary()['request_slots'],49)
            self.assertEqual(flow.read('r101/Shared_initial.json','Shared_initial'),shared)

    def test_target_budget_reset_and_unknown_clearing_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,_,_=fixture(tmp);flow.prepare_continuation()
            flow.ledger.data['continuation_unresolved_requests']=[]
            with self.assertRaises(ValueError):check_binding(flow)
            flow.ledger.data['records'].pop('r101/init/INIT/init/000001')
            with self.assertRaises(BudgetStop):flow.ledger.reserve('new','r101/init','key')

    def test_offline_binding_preserves_review_order_U_and_unknown_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,source,H=fixture(tmp); original=declaration(source)
            with patch('fjsp_usage.research_real.workflow.JsonCandidateTransport',side_effect=AssertionError('no client')):
                ready=flow.prepare_continuation()
                self.assertEqual(flow.prepare_continuation(),ready)
            frozen=flow.read('H_frozen.json','H_frozen')
            self.assertEqual(frozen['members'],H['members'])
            self.assertEqual(frozen['original_frozen_hash'],H['artifact_sha256'])
            self.assertEqual(ready['inherited_U'],2)
            self.assertEqual(ready['initialization_cursor'],4)
            self.assertEqual(ready['next_request_id'],'INIT/init/000004')
            self.assertFalse(ready['dispatch_ready'])
            self.assertEqual(flow.ledger.summary()['request_slots'],6)
            self.assertEqual(flow.ledger.summary()['phase_remaining_slots']['r101/init'],4)
            inherited=flow.ledger.data['records']['r101/init/INIT/init/000003']
            self.assertIsNone(inherited['usage']);self.assertEqual(inherited['status'],'reserved')
            self.assertEqual(inherited['reservation']['output_tokens'],32768)
            self.assertEqual(declaration(source),original)
            with self.assertRaises(BudgetStop):flow.client()
            with self.assertRaises(BudgetStop):flow.ledger.reserve('new','r101/init','key')
            self.assertIsNone(flow._client)
            self.assertFalse((flow.directory/'r101/B0').exists())

    def test_imported_receipts_checked_and_resealing_tampered_review_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,_,_=fixture(tmp);flow.prepare_continuation()
            _,members=flow.h_asset();self.assertEqual(len(members),2)
            state=json.loads((flow.directory/'r101/INIT/checkpoint.json').read_text())
            flow.check_receipts(state['population'])
            changed=deepcopy(state['population'][0]);changed['receipt']['response_text']='forged'
            with self.assertRaises(ValueError):flow.check_receipts([changed])
            H=flow.read('H_frozen.json','H_frozen');H['members'][0]['review']['reviewer']='someone else'
            atomic_json(flow.directory/'H_frozen.json',seal({k:v for k,v in H.items() if k!='artifact_sha256'}))
            with self.assertRaises(ValueError):flow.check_receipts(H['members'])

    def test_changed_limits_source_or_scoring_closure_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,source,_=fixture(tmp)
            for field,value in (('initialization_cap',9),('total_request_cap',101),
                                ('instance_timeout',15),('platform_quota_ceiling',30000001)):
                saved=flow.config;flow.config=replace(saved,**{field:value})
                with self.assertRaises(ValueError):source_evidence(flow)
                flow.config=saved
            flow.protocol['implementation']['files']['code/fjsp_usage/research_real/runtime.py']='bad'
            with self.assertRaises(ValueError):source_evidence(flow)
            (source/'budget.json').write_text((source/'budget.json').read_text()+' ')
            with self.assertRaises(ValueError):source_evidence(flow)
            with self.assertRaises(ValueError):replace(flow.config,purpose='research')

    def test_deleted_failed_or_duplicate_request_slot_rejected_even_with_new_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,source,_=fixture(tmp,interrupted=False)
            budget=json.loads((source/'budget.json').read_text())
            budget['records'].pop('r101/init/INIT/init/000003');atomic_json(source/'budget.json',budget)
            flow.config=replace(flow.config,development_continuation_source=declaration(source))
            with self.assertRaises(ValueError):source_evidence(flow)

    def test_resume_keeps_cursor_and_bounded_new_request_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow,_,_=fixture(tmp,interrupted=False);flow.prepare_continuation()
            class Handwritten:
                identity=digest({'provider':flow.config.payload()['provider'],'mode':'real'})
                calls=[]
                def preflight(self,prompt):pass
                def redact(self,text):return text
                def dispatch(self,key,prompt,*,kind,on_sent):
                    self.calls.append(key);on_sent()
                    c=validate_code('def select_heuristic('+', '.join(U_ARGS)+'):\n    return 1\n')
                    return {'text':'{Handwritten.}\n```python\n'+c.code+'```',
                            'usage':{'input_tokens':10,'output_tokens':20}}
            result={'valid':True,'fitness':-1.,'total_instances':1,
                'instances':[{'file':'tiny.fjs','makespan':10,'lower_bound':10,'score':-1.}]}
            H=flow.read('H_frozen.json','H_frozen')
            members=[validate_code(r['candidate']['code'],kind='h') for r in H['members']]
            def engine():
                return V5BudgetedSearch(flow.directory/'r101/INIT',arm='INIT',
                    config=flow.config.u_search(101),members=members,evaluator=lambda c:result,
                    transport=Handwritten(),context=flow.context,init_phase='r101/init',search_phase='r101/B0',
                    ledger=flow.ledger,experiment=flow.config,training_names=('tiny.fjs',))
            first=engine();self.assertIsNone(first.initialize(stop_after_attempts=1))
            self.assertEqual(first.state['init_cursor'],5)
            self.assertEqual(Handwritten.calls,['r101/init/INIT/init/000004'])
            resumed=engine();self.assertEqual(resumed.state['init_cursor'],5)
            self.assertIsNone(resumed.initialize(stop_after_attempts=1))
            self.assertEqual(resumed.state['init_cursor'],6)
            self.assertEqual(Handwritten.calls[-1],'r101/init/INIT/init/000005')
            self.assertEqual(len(resumed.state['population']),3)
            self.assertEqual(flow.ledger.summary()['phase_remaining_slots']['r101/init'],2)
            self.assertFalse((flow.directory/'r101/Shared_initial.json').exists())


if __name__=='__main__':unittest.main()
