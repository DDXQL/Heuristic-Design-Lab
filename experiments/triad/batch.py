#!/usr/bin/env python3
"""Manifest-driven independent runs; only one generation task at a time."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from experiments.triad import configuration,runtime
DEFAULT=ROOT/'experiments/triad/campaign.pending.json'


def plan(path,engineering=False):
    path=Path(path).resolve();campaign=read(path)
    if campaign['version']!='triad-serial-batch-v1' or campaign['global_generation_tasks']!=1:raise ValueError('single global generation arrangement required; no inferred cross-device limiter')
    rows=[]
    for item in campaign['groups']:
        source=(path.parent/item['config']).resolve();c=configuration.load(source,engineering=engineering)
        if item['group']!=c['group']:raise ValueError('group/config mismatch')
        seeds=c['search_seeds'] or campaign['search_seeds']
        repeats=c['repeat_count'] or campaign['repeat_count']
        if seeds is not None and repeats!=len(seeds):raise ValueError('approved repeats and explicit seed list must match')
        for i,seed in enumerate(seeds or [None]):
            todo=configuration.gaps(c)
            if seeds is not None:todo=[x for x in todo if x not in ('search_seeds','repeat_count')]
            run_id=campaign['campaign_id']+'-'+c['group']+'-seed-'+str(seed) if seed is not None else None
            row=dict(protected_existing_501=(c['group']=='fjsp-u' and seed in (501,502)),group=c['group'],index=i,seed=seed,run_id=run_id,source_config=str(source),config_sha256=sha(source),status='pending' if todo or seed is None else 'configured',pending=todo,budget=configuration.budget({**c,'repeat_count':repeats}))
            existing=ROOT/'preparations/triad/completed'/('FJSP-U'+str(seed)+'.json')
            if c['mode']=='real' and row['protected_existing_501'] and existing.exists():
                record=read(existing);snapshot=record['summary']
                if not record['read_only'] or snapshot['phase']!='completed' or snapshot['evolution_attempts']!=1000:raise ValueError('completed registration receipt invalid')
                row.update(status='completed_read_only',pending=[],existing_registration={'snapshot':snapshot,'source_directory':record.get('source',snapshot.get('source_fetch')),'source_receipt_sha256':sha(existing),'execution_prohibited':True})
            rows.append(row)
    obp_configs={item['group']:configuration.load((path.parent/item['config']).resolve(),engineering=engineering) for item in campaign['groups'] if item['group'].startswith('obp-')}
    if len(obp_configs)==2:
        conditions=('obp_actions','obp_h_abi','obp_bound','data_manifest','solve_seed')
        mismatch=[key for key in conditions if all(c.get(key) is not None for c in obp_configs.values()) and len({digest(c[key]) for c in obp_configs.values()})!=1]
        for row in rows:
            if row['group'].startswith('obp-'):
                row['OBP_contract_version']='obp-feasible-permanent-actions-v2'
                if mismatch:row['pending']+=['shared_OBP_condition:'+key for key in mismatch];row['status']='pending'
    return dict(version='triad-batch-plan-v1',campaign_id=campaign['campaign_id'],campaign_sha256=sha(path),rows=rows,
      all_declared_request_cap=None if any(r['seed'] is None or r['budget']['request_cap_per_seed'] is None for r in rows) else sum(r['budget']['request_cap_per_seed'] for r in rows),
      same_account_generation_tasks=1,API_requests=0,actual_solves=0,credential_reads=0)


def materialize(path,folder,engineering=False):
    path=Path(path).resolve();folder=Path(folder).resolve();p=plan(path,engineering);campaign=read(path)
    target=folder/'Batch.json'
    if target.exists():
        existing=read(target)
        if existing['campaign_sha256']!=sha(path):raise ValueError('batch already frozen with different campaign; no overwrite')
        for row in existing['rows']:
            if sha(row['source_config'])!=row['config_sha256']:raise ValueError('source group config changed; create a new batch-plan revision')
            if row.get('config') and sha(row['config'])!=row['child_config_sha256']:raise ValueError('frozen child config changed')
        return existing
    if folder.exists() and any(folder.iterdir()):raise ValueError('new empty batch-plan directory required')
    folder.mkdir(parents=True,exist_ok=True)
    run_root=(path.parent/campaign['run_root']).resolve()
    if not run_root.is_relative_to(ROOT/'runs'):raise ValueError('independent run root must be inside this release runs/')
    for row in p['rows']:
        if row['seed'] is None:continue
        c=configuration.load(row['source_config'],engineering=engineering)
        c['search_seed']=row['seed'];c['repeat_count']=c['repeat_count'] or campaign['repeat_count'];c['search_seeds']=c['search_seeds'] or campaign['search_seeds']
        dest=folder/'configs'/(row['run_id']+'.json')
        for k in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results','state_delivery'):
            if c.get(k) and isinstance(c[k],str):c[k]=os.path.relpath(c[k],dest.parent)
        if isinstance(c.get('state_delivery'),dict):c['state_delivery']['file']=os.path.relpath(c['state_delivery']['file'],dest.parent)
        write(dest,c);row.update(config=str(dest),child_config_sha256=sha(dest),run_dir=str(run_root/row['run_id']))
    write(target,p);return p


def state(row):
    if row.get('existing_registration'):
        r=row['existing_registration'];return {**r['snapshot'],'phase':'completed','registered_existing':True,'execution_prohibited':True,'registration_source':r['source_directory']}
    if row.get('protected_existing_501'):return {'phase':'existing_501_decision_pending','execution_prohibited':True,'requires_investigation':False}
    if not row.get('run_dir'):return {'phase':'not_started'}
    d=Path(row['run_dir']);p=d/'Protocol.json'
    submissions=[read(f) for f in (d/'submissions').glob('*.json')]
    if any(v.get('state')!='submitted' for v in submissions):return {'phase':'unknown_submission','requires_investigation':True,'submission_receipts':submissions}
    if not p.exists():return {'phase':'not_started'}
    protocol=read(p);s=read(d/'checkpoint.json')
    if protocol.get('version')==runtime.VERSION:
        if (d/'.execution.lock').exists() or (d/'Stop.json').exists():
            return {'phase':s['phase'],'writer_lock':(d/'.execution.lock').exists(),'requires_investigation':s['phase']=='stopped'}
        return {**runtime.Adapter().summary(d),'submission_receipts':submissions}
    if protocol.get('version')=='parent-coverage-routing-v1':
        value=read(d/'exports/summary.json') if (d/'exports/summary.json').exists() else {'phase':s['phase']}
        return {**value,'submission_receipts':submissions,'phase':s['phase'],'writer_lock':(d/'.coordinator.lock').exists(),'requires_investigation':s['phase']=='blocked'}
    raise ValueError('foreign run identity')


def summarize(p):
    rows=[]
    for row in p['rows']:
        try:value=state(row)
        except Exception as x:value={'phase':'evidence_error','error':str(x)}
        rows.append({**row,**value})
    groups=[]
    for group in configuration.GROUPS:
        members=[r for r in rows if r['group']==group];complete=[r for r in members if r['phase']=='completed' and r.get('best_J') is not None]
        js=[r['best_J'] for r in complete]
        curves=[]
        import csv
        for member in members:
            curve={}
            if member.get('existing_registration'):
                curve={point['evolution_attempt']:point['best_J'] for point in member['existing_registration'].get('curve',[])}
            if member.get('run_dir') and not member.get('existing_registration'):
                path=Path(member['run_dir'])/'exports/candidates.csv'
                if path.exists():
                    for point in csv.DictReader(path.open()):
                        if point.get('best_J') not in (None,'') and point.get('evolution_attempt') not in (None,''):
                            curve[int(point['evolution_attempt'])]=float(point['best_J'])
            curves.append(curve)
        curve_summary=[]
        for attempt in sorted({x for curve in curves for x in curve}):
            observed=[curve[attempt] for curve in curves if attempt in curve]
            curve_summary.append({'evolution_attempt':attempt,'observed_runs':len(observed),'mean_J':statistics.mean(observed),'sample_std_J':statistics.stdev(observed) if len(observed)>1 else None})
        groups.append(dict(group=group,J_curve_mean_sample_std=curve_summary,declared_runs=len(members) if all(r['seed'] is not None for r in members) else None,complete_valid_runs=len(js),
           mean_J=statistics.mean(js) if js else None,sample_std_J=statistics.stdev(js) if len(js)>1 else None,
           excluded_from_mean=[{'seed':r['seed'],'phase':r['phase']} for r in members if r not in complete]))
    assets={}
    for row in p['rows']:
        source=row['config'] if row.get('config') else row['source_config']
        c=configuration.load(source,engineering=read(source)['mode']=='mock')
        h=c.get('h_file')
        if h and Path(h).exists():
            key=sha(h)
            if key not in assets:
                cost=c['h_build'].get('source_cost')
                if c['problem']=='fjsp':cost=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['historical_H_build']
                assets[key]={'problem':c['problem'],'H_sha256':key,'historical_source_cost':cost,'new_H_requests_due_to_repetition':0}
    return dict(campaign_id=p['campaign_id'],all_runs=rows,groups=groups,actual_cost=None,shared_H_assets=list(assets.values()),shared_H_cost_counted_per_asset_once=True)


def select(p,group,seed):
    rows=[r for r in p['rows'] if (group is None or r['group']==group) and (seed is None or r['seed']==seed)]
    if not rows:raise ValueError('experiment/seed not in frozen batch')
    return rows


def command(row,action,real=False):
    cmd=[sys.executable,'-s','-B',str(ROOT/'experiments/triad/entry.py'),action,'--config',row['config'],'--run-dir',row['run_dir']]
    c=read(row['config'])
    if c['mode']=='mock':cmd+=['--engineering']
    if real and action in ('prepare','run','resume'):cmd+=['--allow-api','--approve-budget',str(c['api_attempt_cap'])]
    if real and action in ('run','resume'):cmd+=['--allow-solves']
    return cmd


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['plan','prepare','check-only','status','summary','run','resume','pause','export','commands','register-existing','import-existing'])
    ap.add_argument('--campaign',type=Path,default=DEFAULT);ap.add_argument('--batch',type=Path,default=ROOT/'plans/triad-20261113')
    ap.add_argument('--engineering',action='store_true');ap.add_argument('--experiment',choices=configuration.GROUPS);ap.add_argument('--seed',type=int)
    ap.add_argument('--receipt',type=Path);ap.add_argument('--receipt-sha256');ap.add_argument('--accept-existing-completed',action='store_true');ap.add_argument('--all',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-total',type=int)
    a=ap.parse_args()
    if a.action=='plan':print(json.dumps(plan(a.campaign,a.engineering),ensure_ascii=False,indent=2));return 0
    if a.action=='prepare':print(json.dumps(materialize(a.campaign,a.batch,a.engineering),ensure_ascii=False,indent=2));return 0
    p=read(a.batch/'Batch.json')
    for row in p['rows']:
        if row.get('config') and sha(row['config'])!=row['child_config_sha256']:raise ValueError('frozen child changed; no budget reset')
    if a.action in ('status','summary'):
        value=summarize(p)
        if a.action=='summary':
            write(a.batch/'Summary.json',value)
            import csv
            with (a.batch/'all-runs.csv').open('w',newline='') as f:
                columns=['group','index','seed','run_id','phase','initialization_attempts','evolution_attempts','request_reservations','confirmed_sends','unknown_sends','failures','duplicates','best_J','actual_cost']
                w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(value['all_runs'])
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    rows=select(p,a.experiment,a.seed)
    if a.action in ('register-existing','import-existing'):
        if len(rows)!=1:raise ValueError('register exactly one explicitly selected existing run')
        from experiments.triad import registration
        row=rows[0];c=configuration.load(row['config']);receipt=registration.register(row,c,a.accept_existing_completed) if a.action=='register-existing' else registration.accept_receipt(row,c,a.receipt,a.receipt_sha256,a.accept_existing_completed)
        row['existing_registration']=receipt
        # Only this batch registration is written. Never modify the source run.
        write(a.batch/'registrations'/ (row['run_id']+'.json'),receipt);write(a.batch/'Batch.json',p)
        print(json.dumps(receipt,ensure_ascii=False,indent=2));return 0
    if a.action=='check-only':
        output=[]
        for row in rows:
            source=row['config'] if row.get('config') else row['source_config']
            c,data,refs,hs,todo=runtime.preflight(source,a.engineering)
            output.append({'group':row['group'],'seed':row['seed'],'pending':todo,'ready':not todo,'API_requests':0,'actual_solves':0,'credential_reads':0})
        print(json.dumps(output,ensure_ascii=False,indent=2));return 0
    if not a.all and (a.experiment is None or a.seed is None):raise ValueError('select --experiment and --seed, or explicitly --all')
    if a.action=='commands':print(json.dumps([{'run_id':r['run_id'],'run':command(r,'run',real=False),'config_pending':r['pending']} for r in rows if r.get('config')],ensure_ascii=False,indent=2));return 0
    real=[r for r in rows if r.get('config') and read(r['config'])['mode']=='real']
    if real and a.action in ('run','resume'):
        required=sum(r['budget']['request_cap_per_seed'] or 0 for r in real)
        if not a.allow_api or not a.allow_solves or required<=0 or a.approve_total!=required:raise PermissionError('explicit cumulative TOTAL for selected runs, API and solve approval required')
    for row in rows:
        if not row.get('config'):raise PermissionError('seed list still pending')
        phase=state(row)['phase'];action=a.action
        if action in ('run','resume'):
            # A block anywhere in this batch also blocks switching to another seed.
            for other in p['rows']:
                info=state(other)
                if info.get('requires_investigation') or info.get('unknown_sends',0) or info.get('writer_lock'):
                    raise ValueError('another run is active/unknown; preserve evidence and stop batch')
            if phase=='completed':continue
            if action=='run' and phase=='paused':raise ValueError('paused run must resume under its ORIGINAL cap before advancing')
            if phase not in ('not_started','prepared','paused'):raise ValueError('run has a terminal failure; no automatic replacement/refill')
        result=subprocess.run(command(row,action,real=bool(real)),check=False)
        if result.returncode:return result.returncode
        if action in ('run','resume') and state(row)['phase']!='completed':break
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as x:print(json.dumps({'error_type':type(x).__name__,'error':str(x),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
