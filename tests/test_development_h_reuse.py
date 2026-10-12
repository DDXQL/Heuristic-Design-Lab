from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from fjsp_usage.research.candidates import validate_code
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.config import ExperimentConfig, fingerprint
from fjsp_usage.research_real.leafapi import provider
from fjsp_usage.research_real.prompts import prompt_manifest
from fjsp_usage.research_real.development_reuse import source_rows, check_imported_rows
from fjsp_usage.research_real.workflow import Workflow
from fjsp_usage.research_real.assets import seal


def fixture(root):
    root = Path(root); (root/'requirements.txt').write_text('')
    src = root/'runs/source'; (src/'H').mkdir(parents=True)
    c = ExperimentConfig(provider=provider(), mode='real', H_size=2)
    impl = fingerprint(root)
    protocol = {'mode':'real', 'config':c.payload(), 'dataset':{},
                'prompt_pack':prompt_manifest(), 'implementation':impl}
    code = 'def priority(processing_time, remaining_work, remaining_operations, job_ready_time, machine_ready_time, earliest_start, earliest_finish):\n    return -processing_time\n'
    candidate = validate_code(code, description='short processing time', kind='h')
    result = {'valid':True, 'total_instances':1, 'fitness':-1.0,
        'instances':[{'file':'tiny.fjs','makespan':10,'lower_bound':10,'score':-1.0}]}
    row = {'id':'H/init/000000', 'candidate':asdict(candidate), 'fitness':-1.0,'scores':[-1.0]}
    receipt = {'status':'completed','global_key':'H/init/H/init/000000','prompt_key':'prompt',
        'text':'{short processing time}\n```python\n'+code+'```', 'usage':{'input_tokens':10,'output_tokens':20},
        'response_metadata':{'model':c.provider.model}}
    budget = {'identity':digest({'config':c.payload(),'context':digest(protocol)}),
        'records':{receipt['global_key']:{'status':'completed','send_confirmed':True,
                   'prompt_key':'prompt','usage':receipt['usage']}}}
    checkpoint = {'population':[row], 'evaluations':{row['id']:{'status':'completed','result':result}}}
    documents = {'protocol':('protocol.json',protocol),'budget':('budget.json',budget),
        'checkpoint':('H/checkpoint.json',checkpoint),'journal':('H/budgeted_initial_requests.json',{'requests':{row['id']:receipt}})}
    declaration = {'run':'source'}
    for name,(path,body) in documents.items():
        raw=json.dumps(body).encode(); (src/path).write_bytes(raw)
        declaration[name+'_sha256']=hashlib.sha256(raw).hexdigest()
    dev = replace(c,purpose='framework_development',development_h_source=declaration,
                  provider=replace(c.provider,read_timeout=240,total_timeout=300))
    return dev, impl, result


class ReuseTests(unittest.TestCase):
    def test_recursive_development_source_preserves_original_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, impl, result = fixture(tmp); root=Path(tmp)
            rows,audit=source_rows(root,c,{},impl)
            protocol={'mode':'real','config':c.payload(),'dataset':{},'prompt_pack':prompt_manifest(),'implementation':impl}
            asset=seal({'kind':'H_development_source','mode':'real','context':digest(protocol),
                        'population':rows,'audit':audit})
            src=root/'runs/second';(src/'H').mkdir(parents=True)
            (src/'H_development_source.json').write_text(json.dumps(asset))
            checkpoint={'population':[{**rows[0],'source_import_hash':asset['artifact_sha256']}],'evaluations':{}}
            budget={'identity':digest({'config':c.payload(),'context':digest(protocol)}),'records':{}}
            declaration={'run':'second'}
            for name,path,body in [('protocol','protocol.json',protocol),('checkpoint','H/checkpoint.json',checkpoint),
                    ('budget','budget.json',budget),('journal','H/budgeted_initial_requests.json',{'requests':{}})]:
                raw=json.dumps(body).encode();(src/path).write_bytes(raw);declaration[name+'_sha256']=hashlib.sha256(raw).hexdigest()
            next_config=replace(c,development_h_source=declaration,provider=replace(c.provider,stream_response=True))
            again,_=source_rows(root,next_config,{},impl)
            self.assertEqual(again[0]['receipt'],rows[0]['receipt'])
            self.assertEqual(again[0]['origin_context'],rows[0]['origin_context'])
            self.assertNotIn('source_import_hash',again[0])
            asset['population'][0]['receipt']['response_text']='forged'
            (src/'H_development_source.json').write_text(json.dumps(seal({k:v for k,v in asset.items() if k!='artifact_sha256'})))
            with self.assertRaises(ValueError): source_rows(root,next_config,{},impl)

    def test_network_change_reuses_real_receipt_without_reattribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, impl, _ = fixture(tmp)
            rows, audit = source_rows(tmp,c,{},impl)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['id'],'H/source/H/init/000000')
            self.assertEqual(rows[0]['receipt']['global_key'],'H/init/H/init/000000')
            self.assertEqual(audit['original_confirmed_sends'],1)
            with self.assertRaises(ValueError): replace(c,purpose='research')
            with self.assertRaises(ValueError): source_rows(tmp,replace(c,H_seed=8),{},impl)
            with self.assertRaises(ValueError): source_rows(tmp,replace(c,provider=replace(c.provider,model='other')),{},impl)

    def test_source_tampering_or_algorithm_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, impl, _ = fixture(tmp)
            changed={**impl,'files':{**impl['files'],'code/fjsp_usage/scheduler.py':'different'}}
            with self.assertRaises(ValueError): source_rows(tmp,c,{},changed)
            p=Path(tmp)/'runs/source/H/checkpoint.json'; p.write_text(p.read_text()+' ')
            with self.assertRaises(ValueError): source_rows(tmp,c,{},impl)

    def test_full_training_recheck_and_foreign_receipt_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, impl, result = fixture(tmp); root=Path(tmp)
            manifest=root/'manifest.json';manifest.write_text('{}')
            dataset=SimpleNamespace(metadata={},names={'train':('tiny.fjs',)},path=manifest,
                verify=lambda split: None,load=lambda split: ['local instance'],
                evaluate=lambda *args,**kwargs: json.loads(json.dumps(result)))
            workflow=Workflow(root/'runs/target',config=c,dataset=dataset,project_root=root)
            engine=SimpleNamespace(state={'population':[],'attempts':[],'inflight':None,'seen':{}},_save=lambda:None)
            workflow.seed_development_h(engine)
            self.assertEqual(workflow.ledger.summary()['confirmed_sends'],0)
            self.assertEqual(len(engine.state['population']),1)
            workflow.check_receipts(engine.state['population'])
            # Re-sealing altered imported evidence must not detach it from the original response.
            asset=workflow.read('H_development_source.json','H_development_source')
            asset['population'][0]['receipt']['response_text']='forged'
            with self.assertRaises(ValueError):
                originals,audit=source_rows(tmp,c,{},impl);check_imported_rows(asset,originals,audit)
            dataset.evaluate=lambda *args,**kwargs:{**result,'fitness':-2.0}
            different=Workflow(root/'runs/other',config=c,dataset=dataset,project_root=root)
            blank=SimpleNamespace(state={'population':[],'attempts':[],'inflight':None,'seen':{}},_save=lambda:None)
            with self.assertRaises(ValueError): different.seed_development_h(blank)
