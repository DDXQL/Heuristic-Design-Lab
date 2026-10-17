#!/usr/bin/env python3
"""Fair scalar-ID batch: offline prepare/register/check; explicit live execute.

prepare never solves H or creates a provider. register requires fresh approval
and finalized peer handoffs. No validation/test, retry, refill or diagnostic call.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig, fingerprint
from fjsp_usage.research_real.leafapi import KEY_ENV, load_local_key
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.single_fair import (VERSION, AUTH_SCOPE, FairWorkflow,
    source_bundle, bind_history, history_summary, read, file_sha)
from fjsp_usage.research_real.single_report import write_results
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.workflow import ARMS
from run_single_experiments import export_prompts


def prepare(directory, config, dataset, root=ROOT):
    if directory.exists():
        raise ValueError('new offline preparation directory required')
    if config.real_requests_authorized or config.conditional_research['history_binding'] is not None:
        raise ValueError('prepare requires pending config, not inherited live approval')
    docs, members = source_bundle(root,config,dataset)
    dataset.verify('train')  # file hashes only, no parser/evaluator or holdout reads
    with RunLock(directory):
        atomic_json(directory/'config.single.pending.json',config.payload())
        atomic_json(directory/'H_source_binding.json',{
            'source_run':config.conditional_research['source_run'],
            'source_H_hash':docs['H_frozen.json']['artifact_sha256'],
            'code_keys':[m.key for m in members],
            'original_scope_approval':docs['H_frozen.json']['scope_approval'],
            'cached_train_evidence':True,'new_H_evaluations':0,'new_technical_reviews':0})
        export_prompts(directory,members)
        atomic_json(directory/'Preparation.json',{
            'version':VERSION,'status':'OFFLINE_PREPARED_WAITING_FOR_FINAL_PEER_HANDOFF_AND_NEW_APPROVAL',
            'config_sha256':digest(config.payload()),'implementation':fingerprint(root),
            'dataset':dataset.metadata,'new_model_requests':0,'H_reevaluations':0,
            'real_requests_authorized':False,'history_registered':False})


def check_preparation(directory, root=ROOT):
    config = ExperimentConfig.from_dict(read(directory/'config.single.pending.json'))
    dataset = StagedDataset(root/'data/fjsp_manifest.json',project_root=root,mode='real')
    prep = read(directory/'Preparation.json')
    if (prep['implementation'] != fingerprint(root) or prep['dataset'] != dataset.metadata
            or prep['config_sha256'] != digest(config.payload())):
        raise ValueError('offline preparation changed; register a new prepared version')
    source_bundle(root,config,dataset); dataset.verify('train')
    return config,dataset


def register(directory, authorization, additional, root=ROOT):
    config,dataset = check_preparation(directory,root)
    if (directory/'protocol.json').exists():
        raise ValueError('already registered; never replace an existing protocol')
    # Explicit external file; this tool never manufactures a reviewer/approval.
    a = read(authorization)
    if (a.get('approved') is not True or a.get('scope') != AUTH_SCOPE
            or a.get('pending_config_sha256') != digest(config.payload())
            or a.get('max_new_requests') != 60 or not isinstance(a.get('reviewer'),str)
            or not a['reviewer'].strip() or any(t in a['reviewer'] for t in ('填写','placeholder','〔','〕'))
            or a.get('exclusive_caller_branch') != 'codex/u-single-experiments'):
        raise ValueError('actual new batch approval tied to the pending config is required')
    history = bind_history(root,config,dataset,additional)
    payload = config.payload(); payload['real_requests_authorized'] = True
    payload['conditional_research'].update(history_binding=history,authorization=a)
    registered = ExperimentConfig.from_dict(payload)
    docs,_ = source_bundle(root,registered,dataset)
    with RunLock(directory):
        atomic_json(directory/'config.single.authorized.json',registered.payload())
        flow = FairWorkflow(directory,config=registered,dataset=dataset,project_root=root)
        old = docs['H_frozen.json']
        flow.write('H_frozen.json','H_frozen',members=deepcopy(old['members']),member_count=10,
            training_files=old['training_files'],scope_approval=old['scope_approval'],
            source_H_hash=old['artifact_sha256'],source_run=config.conditional_research['source_run'],
            source_mechanism='cached reviewed fixed H; explicit fair-v2 source binding; no new H evaluation')
        flow.h_asset()
        atomic_json(directory/'Human_authorization.json',a)
        atomic_json(directory/'History_binding.json',history)
        with tarfile.open(directory/'registered-snapshot.tar.gz','w:gz') as archive:
            for name in sorted(set(fingerprint(root)['files'])|{'data/fjsp_manifest.json'}):
                archive.add(root/name,arcname=name)
            for name,path in zip(dataset.names['train'],dataset.paths['train']):
                archive.add(path,arcname='train/'+name)
            for name in ('protocol.json','config.single.authorized.json','H_frozen.json',
                         'History_binding.json','Human_authorization.json'):
                archive.add(directory/name,arcname='registration/'+name)
        flow.write('Fair_registration.json','Fair_registration',status='REGISTERED_NOT_STARTED',
            new_model_requests=0,history_binding_hash=history['artifact_sha256'],
            snapshot_sha256=file_sha(directory/'registered-snapshot.tar.gz'))


def report(flow, stop=None):
    results = write_results(flow)
    sends = {arm:sum(r['send_confirmed'] for r in results['requests'] if r['group']==arm) for arm in ARMS}
    completed = results['status']=='completed'
    # A finished generation with unsent slots is not a balanced comparison.
    balanced = completed and all(sends[a]==10 for a in ARMS)
    client = flow._client
    quota = client.inner.quota if client is not None else None
    quota_body = quota.data if quota is not None else (read(flow.directory/'platform_quota.json')
        if (flow.directory/'platform_quota.json').exists() else {})
    unknown_fees=[r['global_key'] for r in results['requests'] if r['send_confirmed']
                  and r['actual_platform_units'] is None]
    infrastructure=[r['global_key'] for r in results['requests']
                    if (r.get('attempt') or {}).get('category')=='api_failure']
    comparison=('balanced_one_seed_training_only' if balanced and not infrastructure else
                'balanced_counts_but_infrastructure_contaminated' if balanced else
                'incomplete_or_unequal_actual_budgets')
    flow.write('Fair_status.json','Fair_status',status='completed' if completed else 'stopped_or_not_started',
        actual_evolution_sends=sends,balanced_actual_request_counts=balanced,
        comparison_status=comparison,infrastructure_failure_keys=infrastructure,
        stop_reason=stop,quota_halted=quota_body.get('halted'),
        budget=flow.ledger.summary(),no_refill=True,no_holdout_access=True,
        interpretation='Equal sends do not imply equal token/solve cost or immunity to infrastructure contamination.')
    b=history_summary(flow.project_root,flow.config)
    atomic_json(flow.directory/'Final_budget_handoff.json',{
        'version':VERSION,'real_caller_active':False,'budget_identity':flow.ledger.identity,
        'budget_sha256':file_sha(flow.directory/'budget.json'),'summary':flow.ledger.summary(),
        'quota_halted':quota_body.get('halted',False),
        'latest_verified_used_points':quota_body.get('observed_used',b['latest_saved_account_used']),
        'old_account_hold':b['retained_account_hold'],'unknown_new_fee_keys':unknown_fees,
        'known_new_points':sum(r['actual_platform_units'] for r in results['requests'] if r['actual_platform_units'] is not None),
        'unknown_new_fee_holds':sum(quota_body.get('records',{}).get(k,{}).get(
            'reserved',flow.config.platform_quota_reservation) for k in unknown_fees),
        'unknown_wire_keys':[r['global_key'] for r in results['requests'] if r['send_confirmed'] and r.get('wire_usage') is None],
        'registered_generation_phases_complete':completed,'unused_initial_slots_are_not_extra_generation_authorization':True,
        'comparison_status':comparison})


def run_training(flow):
    """Stop the WHOLE driver after a gate; never let later arms consume slots."""
    initial=flow.initialize_u(201)
    if initial['status']!='initialized':
        raise BudgetStop('shared initialization incomplete: '+initial['status'])
    for arm in ARMS:
        entry=flow.search_arm(201,arm)
        if entry['status']!='completed':
            raise BudgetStop('stop all arms after first gate: '+arm+' '+entry['status'])
    return flow.search_all()  # completed checkpoints only, never another generation


def execute(directory,env_file,root=ROOT):
    # All offline gates run BEFORE reading a credential or creating any client.
    config = ExperimentConfig.from_dict(read(directory/'config.single.authorized.json'))
    config.check_dispatch(); history_summary(root,config)
    dataset = StagedDataset(root/'data/fjsp_manifest.json',project_root=root,mode='real')
    with RunLock(directory):
        flow = FairWorkflow(directory,config=config,dataset=dataset,project_root=root)
        flow.check()
        os.environ[KEY_ENV] = load_local_key(env_file)
        stop=None
        try:
            run_training(flow)
        except Exception as exc:
            stop=str(exc)[:500]
        finally:
            report(flow,stop)
        if stop: print('停止新增请求：'+stop)


def recover(directory,env_file,root=ROOT):
    """Only metadata GETs, exact receipt recovery; never sends or repeats U."""
    from fjsp_usage.research_real.single_settlement import reconcile
    config=ExperimentConfig.from_dict(read(directory/'config.single.authorized.json'))
    config.check_dispatch();history_summary(root,config)
    dataset=StagedDataset(root/'data/fjsp_manifest.json',project_root=root,mode='real')
    with RunLock(directory):
        flow=FairWorkflow(directory,config=config,dataset=dataset,project_root=root)
        flow.check();os.environ[KEY_ENV]=load_local_key(env_file)
        quota=flow.client().inner.quota
        result=reconcile(flow,quota)
        report(flow,'read-only metadata recovery; no generation requested')
        print(json.dumps({'recovered':result is not None,'model_requests':0},ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','check','register','execute','recover','report'))
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--config',type=Path)
    p.add_argument('--authorization',type=Path)
    p.add_argument('--additional-run',nargs=2,action='append',default=[],metavar=('RUN_DIR','FINAL_HANDOFF'))
    p.add_argument('--env-file',type=Path)
    args=p.parse_args();directory=args.run_dir.resolve()
    if directory.parent != ROOT/'runs':p.error('own worktree runs child required')
    if args.stage=='prepare':
        if not args.config:p.error('explicit pending --config required')
        c=ExperimentConfig.from_dict(read(args.config))
        ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
        prepare(directory,c,ds)
    elif args.stage=='check':
        c,_=check_preparation(directory)
        registered=(directory/'config.single.authorized.json').exists()
        if registered:
            c=ExperimentConfig.from_dict(read(directory/'config.single.authorized.json'))
            b=history_summary(ROOT,c)
            from fjsp_usage.research_real.single_experiments import budget_inventory,worktree_roots
            if budget_inventory(worktree_roots(ROOT),exclude=directory)!=b['real_budget_inventory']:
                raise BudgetStop('peer budget/writer changed after registration')
        print(json.dumps({'status':'registered-not-dispatched-by-check' if registered else 'offline-prepared',
            'authorized':c.real_requests_authorized,'history_registered':registered,'network_requests':0}))
    elif args.stage=='register':
        if not args.authorization:p.error('explicit new --authorization file required')
        register(directory,args.authorization,args.additional_run)
    elif args.stage in ('execute','recover'):
        if not args.env_file:p.error('explicit --env-file required')
        (execute if args.stage=='execute' else recover)(directory,args.env_file)
    else:
        c=ExperimentConfig.from_dict(read(directory/'config.single.authorized.json'))
        ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
        with RunLock(directory):report(FairWorkflow(directory,config=c,dataset=ds,project_root=ROOT))


if __name__=='__main__':main()
