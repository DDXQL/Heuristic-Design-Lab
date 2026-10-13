"""Handwritten loopback responses and toys; never real candidate assets."""
from dataclasses import asdict
from fjsp_usage.research.candidates import U_ARGS,H_ARGS,validate_code
from fjsp_usage.research_real.fixtures import fixture_server
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.research_real.staged_evaluation import create_synthetic_dataset,StagedDataset
from fjsp_usage.research.events import atomic_json
from .config import UsageConfig
from .workflow import UsageWorkflow
from . import VERSION


def response(payload,index):
    key=payload['request_id']
    marker=1 if index==2 else index  # one true code repeat during shared init
    if '/B/' in key:
        if index==18:code='not Python'
        else:code='def use_heuristics('+', '.join(U_ARGS)+'):\n    return (1, (3 + progress * '+str(marker/100)+', 2, 0))\n'
    else:
        if '/A/' in key and index==9:code='def use_heuristics('+', '.join(U_ARGS)+'):\n    return (1,(1,1,0))\n'  # A policy failure
        else:code='def use_heuristics('+', '.join(U_ARGS)+'):\n    return (0, (progress * '+str(marker/100)+', 1, -1))\n'
    return {'text':'{Handwritten local synthetic fixture, not real model generation.}\n```python\n'+code+'```',
        'usage':{'input_tokens':64,'output_tokens':48},'finish_reason':'stop'}


def acceptance(directory,root):
    if directory.exists():raise ValueError('synthetic acceptance requires a new directory')
    from fjsp_usage.research_real.locking import RunLock
    with RunLock(directory):return _acceptance_locked(directory,root)


def _acceptance_locked(directory,root):
    manifest=create_synthetic_dataset(directory/'toy-data',count=2)
    # A single synthetic 503 occupies one ordinary A slot; it is never retried.
    with fixture_server(responder=response,script=tuple({} for _ in range(7))+({'status':503},)) as (url,state):
        cfg=UsageConfig(provider=ProviderConfig(url,'HANDWRITTEN-LOCAL-FIXTURE'),mode='synthetic',
            H_size=3,H_initialization_cap=3,population_size=5,cross_parents=5,mutation_parents=1,
            initialization_cap=20,generations=1,attempts_per_generation=10,seeds=(301,),
            instance_timeout=10,review_timeout=3,total_request_cap=40,training_diagnostics=True)
        dataset=StagedDataset(manifest,project_root=manifest.parent,mode='synthetic')
        flow=UsageWorkflow(directory,config=cfg,dataset=dataset,project_root=root)
        rules=[]
        for body in ('return -earliest_finish','return remaining_work-processing_time','return 0'):
            rules.append(validate_code('def priority('+', '.join(H_ARGS)+'):\n    '+body+'\n',kind='h'))
        flow.write('Handwritten_H_fixture.json','Handwritten_H_fixture',members=[asdict(h) for h in rules],
            notice='Handwritten toy H, no human research review or real generation.')
        atomic_json(directory/'config.synthetic.json',cfg.payload())
        gate=flow.search_all();report=flow.training_report()
        initial=flow.read('r301/Shared_initial.json','Shared_initial')
        finals=[flow.read(f'r301/{a}/Final_population.json','Final_population') for a in ('A','B')]
        assert all(f['shared_initial_hash']==initial['artifact_sha256'] for f in finals)
        for a in ('A','B'):
            import json
            checkpoint=json.loads((directory/f'r301/{a}/checkpoint.json').read_text())
            assert len(checkpoint['attempts'])==10
            assert [x['operator'] for x in checkpoint['attempts']]==['CROSS']*5+['MUTATE']*5
        assert all(s=='train' for s,n in dataset.opened)
        evidence=flow.write('Synthetic_acceptance.json','Synthetic_acceptance',
            new_real_requests=0,fixture_dispatches=len(state['requests']),shared_initial_hash=initial['artifact_sha256'],
            entries=gate['entries'],report_hash=report['artifact_sha256'],opened=dataset.opened,
            notice='Handwritten HTTP responses and independent toy files; no benchmark results or real initial candidates.')
        return evidence
