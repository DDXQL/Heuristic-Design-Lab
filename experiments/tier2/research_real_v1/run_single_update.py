#!/usr/bin/env python3
"""Bounded fixed-H/P0 update-frequency trial; no initialization or holdouts."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_seal
from fjsp_usage.research_real.config import ExperimentConfig,fingerprint
from fjsp_usage.research_real.single_update import VERSION,SCOPE,UpdateWorkflow,source_bundle,bind_history
from fjsp_usage.research_real.single_fair import file_sha,read,history_summary
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.leafapi import load_local_key,KEY_ENV


def prepared(directory):
    c=ExperimentConfig.from_dict(read(directory/'config.pending.json'))
    ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    p=read(directory/'Preparation.json')
    if p!={'config_sha256':digest(c.payload()),'implementation':fingerprint(ROOT),'dataset':ds.metadata}:
        raise ValueError('prepared code/config/data changed')
    source_bundle(ROOT,c,ds);ds.verify('train')
    return c,ds


def prepare(directory,config):
    if directory.exists():raise ValueError('new independent directory required')
    c=ExperimentConfig.from_dict(read(config))
    if c.real_requests_authorized:raise ValueError('prepare takes pending config only')
    ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    source_bundle(ROOT,c,ds);ds.verify('train')
    with RunLock(directory):
        atomic_json(directory/'config.pending.json',c.payload())
        atomic_json(directory/'Preparation.json',{'config_sha256':digest(c.payload()),
            'implementation':fingerprint(ROOT),'dataset':ds.metadata})


def register(directory,authorization):
    c,ds=prepared(directory)
    if (directory/'protocol.json').exists():raise ValueError('already registered; never overwrite')
    a=read(authorization)
    if (a.get('approved') is not True or a.get('scope')!=SCOPE or a.get('max_new_requests')!=60
        or a.get('pending_config_sha256')!=digest(c.payload()) or not a.get('authorization_excerpt')):
        raise ValueError('current user authorization bound to exact config required')
    history=bind_history(ROOT,c,ds);docs,_,rng=source_bundle(ROOT,c,ds)
    payload=c.payload();payload['real_requests_authorized']=True
    payload['conditional_research'].update(authorization=a,history_binding=history)
    registered=ExperimentConfig.from_dict(payload)
    ref=c.conditional_research['historical_reference'];refroot=ROOT/'runs'/ref['run']
    for n,h in ref['files_sha256'].items():
        if file_sha(refroot/n)!=h:raise ValueError('historical reference changed')
    rp=read(refroot/'protocol.json');old=read(refroot/'r201/Shared_initial.json')
    check_seal(old,kind='Shared_initial',mode='real',context=digest(rp))
    if rp['dataset']!=ds.metadata or old['training_files']!=list(ds.names['train']):
        raise ValueError('historical reference data/order differs')
    best=sorted(old['population'],key=lambda x:(-x['fitness'],x['id']))[0]
    if best['candidate']['key'] in {x['candidate']['key'] for x in docs['r201/Shared_initial.json']['population']}:
        raise ValueError('historical champion must not be imported')
    with RunLock(directory):
        atomic_json(directory/'config.authorized.json',registered.payload())
        flow=UpdateWorkflow(directory,config=registered,dataset=ds,project_root=ROOT)
        H=docs['H_frozen.json'];shared=docs['r201/Shared_initial.json']
        asset=flow.write('H_frozen.json','H_frozen',members=deepcopy(H['members']),member_count=10,
            training_files=H['training_files'],scope_approval=H['scope_approval'],source_run=c.conditional_research['source_run'],
            source_H_hash=H['artifact_sha256'],source_mechanism='unchanged cached H; no new technical review/evaluation')
        flow.write('r201/Shared_initial.json','Shared_initial',seed=201,H_hash=asset['artifact_sha256'],
            training_files=shared['training_files'],population=deepcopy(shared['population']),
            source_run=c.conditional_research['source_run'],source_shared_hash=shared['artifact_sha256'],
            source_receipts_unchanged=True,new_initial_requests=0)
        atomic_json(directory/'Parent_rng_initial.json',{'rng':rng,'sha256':digest(rng),'seed':201})
        atomic_json(directory/'History_binding.json',history);atomic_json(directory/'Human_authorization.json',a)
        atomic_json(directory/'Frozen_historical_reference.json',{'role':'historical only; never a parent',
            'source':ref,'row':best,'new_evaluations':0})
        with tarfile.open(directory/'registered-snapshot.tar.gz','w:gz') as t:
            for n in sorted(fingerprint(ROOT)['files']):t.add(ROOT/n,arcname=n)
            t.add(ROOT/'data/fjsp_manifest.json',arcname='data/fjsp_manifest.json')
            for n,p in zip(ds.names['train'],ds.paths['train']):t.add(p,arcname='train/'+n)
            for n in ('config.authorized.json','protocol.json','H_frozen.json','r201/Shared_initial.json',
                      'Parent_rng_initial.json','History_binding.json','Human_authorization.json','Frozen_historical_reference.json'):
                t.add(directory/n,arcname='registration/'+n)
        flow.write('Registration.json','Update_registration',source_H_hash=H['artifact_sha256'],
            source_initial_hash=shared['artifact_sha256'],initial_rng_sha256=digest(rng),
            no_new_initial_requests=True,no_new_H_evaluations=True,
            snapshot_sha256=file_sha(directory/'registered-snapshot.tar.gz'))


def report(flow,stop=None):
    p=flow.directory;records=flow.ledger.data['records'];quota=read(p/'platform_quota.json') if (p/'platform_quota.json').exists() else {}
    points=0;unknown=[];arms={}
    for key,r in records.items():
        stem=hashlib.sha256(key.encode()).hexdigest()+'.json';bill=read(p/'billing'/stem) if (p/'billing'/stem).exists() else {}
        value=bill.get('actual_platform_units') if bill.get('status')=='invoice_account_matched' else None
        proof=p/'billing_reconciliations'/stem
        if proof.exists():
            proof=read(proof)
            if proof['original_billing_sha256']!=file_sha(p/'billing'/stem):raise ValueError('receipt changed')
            for n,h in proof['evidence_files_sha256'].items():
                if file_sha(p/n)!=h:raise ValueError('settlement evidence changed')
            value=proof['actual_platform_units']
        if value is not None:points+=value
        elif r.get('send_confirmed'):unknown.append(key)
    for arm in ('A','B'):
        path=p/f'r201/{arm}/checkpoint.json';s=read(path) if path.exists() else {}
        arms[arm]={'phase':s.get('phase','not_started'),'slots':len(s.get('attempts',[])),
            'confirmed_sends':sum(bool(r.get('send_confirmed')) for r in records.values() if r['phase']==f'r201/{arm}'),
            'cursor':s.get('cursor'),'generation':s.get('generation'),
            'inflight':s.get('inflight',{}).get('id') if s.get('inflight') else None}
    done=all(x['phase']=='completed' and x['slots']==30 for x in arms.values())
    flow.write('Update_status.json','Update_status',status='completed' if done else 'stopped_or_not_started',
        arms=arms,stop_reason=stop,known_new_points=points,unknown_new_fee_keys=unknown,
        no_new_initial_requests=True,no_holdout_access=True)
    b=history_summary(ROOT,flow.config)
    atomic_json(p/'Final_budget_handoff.json',{'version':VERSION,'real_caller_active':False,
        'budget_identity':flow.ledger.identity,'budget_sha256':file_sha(p/'budget.json'),'summary':flow.ledger.summary(),
        'registered_generation_phases_complete':done,'quota_halted':quota.get('halted',False),
        'latest_verified_used_points':quota.get('observed_used',b['latest_saved_account_used']),
        'old_account_hold':b['retained_account_hold'],'known_new_points':points,'unknown_new_fee_keys':unknown,
        'unknown_new_fee_holds':sum(quota['records'][k]['reserved'] for k in unknown),
        'unknown_wire_keys':[k for k,r in records.items() if r.get('send_confirmed') and r.get('usage') is None],
        'no_refill':True,'generation_remaining':{a:30-x['slots'] for a,x in arms.items()}})


def load_flow(directory):
    c=ExperimentConfig.from_dict(read(directory/'config.authorized.json'));history_summary(ROOT,c)
    ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    return UpdateWorkflow(directory,config=c,dataset=ds,project_root=ROOT)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stage',choices=['prepare','register','check','execute','recover','report'])
    ap.add_argument('--run-dir',type=Path,required=True);ap.add_argument('--config',type=Path)
    ap.add_argument('--authorization',type=Path);ap.add_argument('--env-file',type=Path)
    args=ap.parse_args();p=args.run_dir.resolve()
    if p.parent!=ROOT/'runs':ap.error('own runs directory required')
    if args.stage=='prepare':prepare(p,args.config);return
    if args.stage=='register':register(p,args.authorization);return
    if args.stage=='check':
        if (p/'.writer.lock').exists():raise RuntimeError('active writer; do not open another workflow')
        prepared(p)
        if (p/'protocol.json').exists():load_flow(p).check()
        print(json.dumps({'offline_checks_passed':True,'network_queries':0}));return
    with RunLock(p):
        flow=load_flow(p);flow.check();stop=None
        try:
            if args.stage in ('execute','recover'):
                flow.config.check_dispatch()
                if not args.env_file:ap.error('--env-file required for actual execution or metadata recovery')
                os.environ[KEY_ENV]=load_local_key(args.env_file)
                if args.stage=='execute':flow.run_training()
                else:
                    from fjsp_usage.research_real.single_settlement import reconcile
                    reconcile(flow,flow.client().inner.quota)
        except Exception as exc:stop=str(exc)[:500]
        finally:report(flow,stop)
        if stop:print('停止新增请求：'+stop,flush=True)

if __name__=='__main__':main()
