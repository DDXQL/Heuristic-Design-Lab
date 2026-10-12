#!/usr/bin/env python3
"""Offline-only state audit and bounded paired research proposal; no credentials.

Creates a NEW directory. Old U are audited unchanged, not imported as scored
research candidates. Only training instances are parsed/solved. Holdout files
are optionally byte-hashed for identity, never parsed or evaluated here.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.conditional_research import VERSION,prepare,check_origin
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.workflow import Workflow
from fjsp_usage.research_real.assets import checked_candidate
from fjsp_usage.research_real.runtime import evaluate
from fjsp_usage.research_real.state_diagnostics import static_diagnostics,state_contract
from fjsp_usage.research_real.initialization import selector_signature
from fjsp_usage.research_real.prompts import prompt_manifest

SOURCE='leaf-tier2-single-P-acceptance-20261010-v4'


def data_history(manifest, protected):
    names={split:set(manifest['split'][split]) for split in ('train','validation','test')}
    evidence={s:[] for s in names}
    files=[ROOT/p for p in protected if p.endswith('.json')]
    files+=list((ROOT/'baselines/tier1_single_rule_v1/records').rglob('*.json'))
    def walk(x, path):
        if isinstance(x,dict):
            # Actual numeric per-instance results only, not manifest/protocol
            # references to unopened holdouts.
            name=x.get('file',x.get('name',x.get('instance')))
            if isinstance(name,str) and 'makespan' in x and any(k in x for k in ('score','normalized_score','feasible')):
                for split,members in names.items():
                    if name in members: evidence[split].append({'asset':path,'file':name})
            for v in x.values(): walk(v,path)
        elif isinstance(x,list):
            for v in x: walk(v,path)
    for path in files:
        try: walk(json.loads(path.read_text()),str(path.relative_to(ROOT)))
        except (ValueError,UnicodeError): pass
    return {'evaluated_file_evidence':{s:sorted({r['file'] for r in e}) for s,e in evidence.items()},
        'evidence_sources':{s:sorted({r['asset'] for r in e}) for s,e in evidence.items()},
        'validation_prior_usage':'All 11 used for historical single-rule baseline selection; not globally pristine.',
        'test_prior_usage':'No numeric test makespan evidence found in scanned repository assets; absence of logs does not prove no external use.',
        'scope':'Repository runs and baseline JSON; does not certify all external EoH-S/Codex files.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--audit-u',action='store_true')
    args=parser.parse_args(); directory=args.run_dir.resolve()
    if directory.parent!=ROOT/'runs' or directory.exists(): parser.error('requires a new runs child; never overwrites or resumes')
    protected={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'runs').rglob('*') if p.is_file()}
    if any(p.endswith('/.writer.lock') for p in protected): parser.error('existing writer lock; inspect before preparing')
    source=ROOT/'runs'/SOURCE; old=json.loads((source/'config.development.authorized.json').read_text())
    config={**old,'purpose':'research','real_requests_authorized':False,
        'development_h_source':None,'development_continuation_source':None,'development_acceptance':None,
        'population_size':5,'cross_parents':5,'mutation_parents':1,'seeds':[201],
        'initialization_cap':20,'generations':1,'attempts_per_generation':10,'total_request_cap':60,
        'training_diagnostics':True,
        'phase_request_caps':{'H/init':100,'H/search':20,'r201/init':20,
            **{f'r201/{arm}':10 for arm in ('B0','B1','B2','P')}},
        'conditional_research':{'version':VERSION,'source_run':SOURCE,
            'source_files_sha256':{name.removeprefix('runs/'):sha for name,sha in protected.items()
                if len(Path(name).parts)>=3},
            'history_batches':['leaf-framework-30pct-20261009-v1','leaf-framework-30pct-20261009-v2',SOURCE],
            'lifetime_request_cap':300,'scope_approval':None,
            'baseline_policy':'validation_select_one_report_all_train',
            'holdout_policy':'locked_until_protocol_and_search_complete'}}
    cfg=ExperimentConfig.from_dict(config)
    dataset=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    with RunLock(directory),patch('fjsp_usage.research_real.workflow.JsonCandidateTransport',side_effect=AssertionError('offline only')):
        atomic_json(directory/'config.research.pending.json',cfg.payload())
        flow=Workflow(directory,config=cfg,dataset=dataset,project_root=ROOT)
        print('离线核对10条H的完整训练评价；不创建模型客户端。',flush=True)
        prepared=prepare(flow); H,members,_=check_origin(ROOT,cfg,dataset)
        # Byte hashing is identity verification, not holdout parsing/selection.
        verified={}
        for split in dataset.names:
            verified[split]=[]
            for name,path in zip(dataset.names[split],dataset.paths[split]):
                sha=hashlib.sha256(path.read_bytes()).hexdigest()
                if sha!=dataset.manifest['files'][name]['sha256']: raise ValueError('split byte hash mismatch: '+name)
                verified[split].append({'file':name,'sha256':sha,'parsed_or_solved_here':split=='train'})
        history=data_history(dataset.manifest,protected)
        # Explicit historical baseline records establish validation exposure even
        # when legacy per-instance row names differ from the current schema.
        history['validation_evidence']='baselines/tier1_single_rule_v1/portable_manifest.json:selection criterion/partition validation; records/*/evaluation_result.json'
        audit=[]
        if args.audit_u:
            origin=ROOT/'runs/leaf-framework-30pct-20261010-v3'
            paths=[origin/'r101/INIT/checkpoint.json',source/'r101/P/checkpoint.json']
            journals=[origin/'r101/INIT/budgeted_initial_requests.json',source/'r101/P/budgeted_evolution_requests.json']
            instances=dataset.load('train'); all_codes={}
            from fjsp_usage.research.candidates import parse_response
            for path,journal in zip(paths,journals):
                state=json.loads(path.read_text()); records=json.loads(journal.read_text())['requests']
                for identifier,cached in state['evaluations'].items():
                    if not cached.get('result',{}).get('valid'): continue
                    candidate=parse_response(records[identifier]['text'],kind='U')
                    all_codes[candidate.key]=(identifier,candidate,path,cached['result'])
            for key,(identifier,candidate,path,old_result) in all_codes.items():
                print('训练轨迹核对：'+identifier,flush=True)
                result=evaluate(candidate,members,instances,dataset.names['train'],timeout=cfg.instance_timeout,diagnostics=True)
                item={'id':identifier,'candidate':asdict(candidate),'source_checkpoint':str(path.relative_to(ROOT)),
                    'source_checkpoint_sha256':protected[str(path.relative_to(ROOT))],
                    'old_fitness':old_result['fitness'],'new_protocol_result':result,
                    'same_training_makespans':result['valid'] and [r['makespan'] for r in result['instances']]==
                        [r['makespan'] for r in old_result['instances']],
                    'static_diagnostics':static_diagnostics(candidate.code,len(members)),
                    'narrow_signature':selector_signature(candidate.code)}
                audit.append(item); atomic_json(directory/'Historical_U_state_audit.json',audit)
        account=prepared['history']; reserve=cfg.platform_quota_reservation
        final={'status':'OFFLINE_READY_PENDING_ACTUAL_RESEARCH_SCOPE_AND_REQUEST_AUTHORIZATION',
            'new_generation_requests':0,'new_H_generated':0,'imported_initial_U':0,
            'proposal':{'scope':'one-seed preliminary paired conditional fixed-existing-H research',
                'arms':['B0','B1','B2','P'],'seed':201,'N':5,'cross_parents':5,'mutation_parents':1,
                'generations':1,'slots_per_arm':10,'fresh_initialization_cap':20,'new_request_cap':60,
                'initialization_failure_rule':'retain all outcomes; stop without N reduction, hand-written injection or extra requests',
                'baseline':'all 10 fixed h training results; choose one once by validation, never by test',
                'expansion':'not authorized; require a separately registered version with new seed/generation caps before more calls',
                'validation_test':'no evaluation this preparation; separate stages after search/protocol freeze; test once on selected assets'},
            'historical_budget':account,
            'proposed_max_lifetime_slots':account['historical_request_slots']+60,
            'saved_quota_preflight':{'used':account['latest_saved_account_used'],'retained_hold':account['retained_account_hold'],
                'next_reservation':reserve,'ceiling':cfg.platform_quota_ceiling,
                'safe_headroom_before_next_reservation':cfg.platform_quota_ceiling-account['latest_saved_account_used']-account['retained_account_hold'],
                'next_would_fit_saved_balance':account['latest_saved_account_used']+account['retained_account_hold']+reserve<=cfg.platform_quota_ceiling,
                'notice':'Not a live quota query, not forecast cost; fresh account check required on dispatch. Total 60 calls not guaranteed by saved balance.'},
            'split_identity':verified,'dataset_history':history,'state_contract':state_contract(),
            'H_reassessed':len(prepared['rows']),'H_valid':sum(r['result']['valid'] for r in prepared['rows']),
            'old_U_audited':len(audit),'old_U_reproduced':sum(r['same_training_makespans'] for r in audit),
            'prompt_comparison':{'current':prompt_manifest(),
                'previous_prompt_version':json.loads((source/'protocol.json').read_text())['prompt_pack']['version'],
                'changed_sections':[k for k,v in prompt_manifest()['sections'].items()
                    if json.loads((source/'protocol.json').read_text())['prompt_pack']['sections'].get(k)!=v],
                'changed_factor':'Normalized-state bound disclosure only; novelty archive/instructions and narrow dedup unchanged from v4.',
                'real_v5_initialization_requests':0,'repeat_rate_improvement':'not measured'},
            'holdouts_parsed_or_solved_here':0,'source_run_files_unchanged':all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h for n,h in protected.items())}
        atomic_json(directory/'Research_readiness.json',final)
        atomic_json(directory/'Protected_source_hashes.json',protected)
        print(json.dumps({k:final[k] for k in ('status','H_valid','old_U_audited','old_U_reproduced','proposed_max_lifetime_slots','saved_quota_preflight')},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
