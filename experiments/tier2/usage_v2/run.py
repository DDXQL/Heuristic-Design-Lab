#!/usr/bin/env python3
"""Explicit training-only SELECT/MIX ablation; no implicit model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.conditional_research import prepare,freeze_h,check_origin
from fjsp_usage.usage_v2.config import UsageConfig
from fjsp_usage.usage_v2.workflow import UsageWorkflow
from fjsp_usage.usage_v2.exports import export_prompts

SOURCE='leaf-tier2-single-P-acceptance-20261010-v4'


def pending_config():
    protected={str(p.relative_to(ROOT/'runs')):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'runs').rglob('*') if p.is_file() and len(p.relative_to(ROOT/'runs').parts)>=2}
    if any(p.endswith('/.writer.lock') for p in protected):raise ValueError('existing writer lock; inspect, do not terminate or duplicate')
    source=json.loads((ROOT/'runs'/SOURCE/'config.development.authorized.json').read_text())
    prior=json.loads((ROOT/'runs/conditional-paired-research-20261011-v4/config.research.pending.json').read_text())
    d={**prior['conditional_research'],'source_files_sha256':protected,'scope_approval':None}
    config={**source,'purpose':'research','real_requests_authorized':False,
        'development_h_source':None,'development_continuation_source':None,'development_acceptance':None,
        'population_size':5,'cross_parents':5,'mutation_parents':1,'seeds':[301],
        'initialization_cap':20,'generations':1,'attempts_per_generation':10,'total_request_cap':40,
        'training_diagnostics':True,'conditional_research':d,
        'phase_request_caps':{'r301/init':20,'r301/A':10,'r301/B':10}}
    return UsageConfig.from_dict(config)


def offline_prepare(directory,config):
    dataset=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    with RunLock(directory),patch('fjsp_usage.research_real.workflow.JsonCandidateTransport',side_effect=AssertionError('offline prepare forbids provider creation')):
        flow=UsageWorkflow(directory,config=config,dataset=dataset,project_root=ROOT)
        atomic_json(directory/'config.pending.json',config.payload())
        print('Reassessing all ten fixed H on train21; no model client, no holdout files.',flush=True)
        evidence=prepare(flow)
        source,members,_=check_origin(ROOT,config,dataset)
        exported=export_prompts(directory/'prompts',members,config.provider.max_prompt_bytes)
        history=evidence['history']
        ready=flow.write('Preparation.json','Preparation',new_generation_requests=0,
            H_reassessed=len(evidence['rows']),H_valid=sum(r['result']['valid'] for r in evidence['rows']),
            H_makespans_reproduced=sum(r['same_training_makespans_as_source'] for r in evidence['rows']),
            original_H_hash=source['artifact_sha256'],ordered_H_keys=[m.key for m in members],
            proposal={'seed':301,'N':5,'initialization_cap':20,'arms':{'A':'SELECT only','B':'SELECT or MIX'},
                'generations':1,'slots_per_arm':10,'cross_per_arm':5,'mutation_per_arm':5,'max_new_requests':40},
            history=history,max_lifetime_slots=history['historical_request_slots']+40,
            saved_account_preflight={'used':history['latest_saved_account_used'],'retained_hold':history['retained_account_hold'],
                'next_reservation':config.platform_quota_reservation,'ceiling':config.platform_quota_ceiling,
                'next_fits_saved_record':history['latest_saved_account_used']+history['retained_account_hold']+config.platform_quota_reservation<=config.platform_quota_ceiling,
                'notice':'Saved balance only; refresh on dispatch; no certified monetary/token upper bound, no guarantee all forty calls fit.'},
            prompt_comparison=exported['comparison'],opened=dataset.opened,
            research_H_scope_approved=config.conditional_research['scope_approval'] is not None,
            request_authorized=config.real_requests_authorized,
            status='OFFLINE_PREPARED_PENDING_NEW_H_SCOPE_AND_PAID_REQUEST_AUTHORIZATION')
        flow.training_report()
        print(json.dumps({k:ready[k] for k in ('status','H_valid','H_makespans_reproduced','max_lifetime_slots')},ensure_ascii=False),flush=True)
        return ready


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','synthetic-acceptance','freeze-h','initialize','search-arm','search','report','examples','compatibility'))
    p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--config',type=Path)
    p.add_argument('--seed',type=int,default=301);p.add_argument('--arm',choices=('A','B'))
    args=p.parse_args();directory=args.run_dir.resolve()
    if args.stage in ('prepare','synthetic-acceptance','examples'):
        if directory.exists():p.error('create a new directory; never overwrite existing run assets')
        if args.stage=='synthetic-acceptance':
            from fjsp_usage.usage_v2.fixtures import acceptance
            print(json.dumps(acceptance(directory,ROOT),ensure_ascii=False));return
        if args.stage=='examples':
            from fjsp_usage.usage_v2.examples import write_examples
            print(json.dumps(write_examples(directory),ensure_ascii=False));return
        if directory.parent!=ROOT/'runs':p.error('real preparation requires a new direct project runs child')
        config=UsageConfig.from_dict(json.loads(args.config.read_text())) if args.config else pending_config()
        offline_prepare(directory,config);return
    if not args.config:p.error('explicit bound --config required')
    if directory.parent!=ROOT/'runs':p.error('real stages require a direct project runs child')
    config=UsageConfig.from_dict(json.loads(args.config.read_text()))
    dataset=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode=config.mode)
    with RunLock(directory):
        flow=UsageWorkflow(directory,config=config,dataset=dataset,project_root=ROOT)
        if args.stage=='compatibility':
            from fjsp_usage.usage_v2.compatibility import audit
            result=audit(flow)
        elif args.stage=='freeze-h':result=freeze_h(flow)
        elif args.stage=='initialize':result=flow.initialize_u(args.seed)
        elif args.stage=='search-arm':
            if not args.arm:p.error('--arm required')
            result=flow.search_arm(args.seed,args.arm)
        elif args.stage=='search':result=flow.search_all()
        else:result=flow.training_report()
        print(json.dumps({'stage':args.stage,'result_kind':result.get('kind'),'status':result.get('status'),'new_slots':len(flow.ledger.data['records'])},ensure_ascii=False))

if __name__=='__main__':main()
