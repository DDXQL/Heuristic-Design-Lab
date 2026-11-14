#!/usr/bin/env python3
"""Finite Slurm-supervised list of existing independent entry commands, no search loop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import batch,configuration
from experiments.triad.concurrency_probe import claim


def can_advance(state):
    return state.get('phase')=='completed' and not state.get('requires_investigation') and not state.get('unknown_sends',0) and not state.get('writer_lock',False)


def prepare(batch_dir,items,folder,approve):
    plan=read(Path(batch_dir)/'Batch.json');rows=[]
    if len(items)>5 or len(items)!=len(set(items)):raise ValueError('finite distinct FJSP list, at most five new runs')
    for text in items:
        group,seed=text.split(':');row=batch.select(plan,group,int(seed))[0]
        if row.get('protected_existing_501') or row.get('existing_registration'):raise PermissionError('old501 only read-only in summary, never in executable queue')
        c=configuration.load(row['config']);gaps=configuration.gaps(c)
        if c['problem']!='fjsp' or gaps:raise PermissionError('queue item not frozen: '+text+' '+str(gaps))
        rows.append(row)
    total=sum(configuration.load(r['config'])['api_attempt_cap'] for r in rows)
    if not rows or approve!=total:raise PermissionError('manual inclusive total for ALL selected runs required')
    folder=Path(folder)
    if folder.exists():raise FileExistsError('queue identity exists; original resume only, no overwrite')
    folder.mkdir(parents=True);write(folder/'Queue.json',{'version':'finite-serial-queue-v1','batch':str(Path(batch_dir).resolve()),'rows':rows,'total_original_request_cap':total,'resource_request':{'cpus':4,'memory_mib':4096,'wall_seconds':43200,'drain_seconds':1260},'automatic_retry':False,'independent_searches_parallel':False})
    write(folder/'checkpoint.json',{'phase':'prepared','cursor':0,'total_original_request_cap':total,'history':[]});return read(folder/'Queue.json')


def pause(folder):
    folder=Path(folder);s=read(folder/'checkpoint.json');p=read(folder/'Queue.json');write(folder/'Pause.json',{'at':time.time(),'scope':'original queue and current child only'})
    if s.get('active_child'):
        row=p['rows'][s['cursor']];subprocess.run(batch.command(row,'pause'),check=True)
    return {'requested':True,'no_new_requests':True}


def work(folder,approve,resume=False):
    folder=Path(folder);p=read(folder/'Queue.json');s=read(folder/'checkpoint.json')
    if approve!=p['total_original_request_cap'] or approve!=s['total_original_request_cap']:raise PermissionError('resume inherits original ALL-run cap')
    if not os.environ.get('SLURM_JOB_ID'):raise PermissionError('real queue must be Slurm supervised, not a Mac/SSH process')
    if s['phase']!=('paused' if resume else 'prepared'):raise ValueError('prepared initial queue or safely paused original queue required')
    claim(folder/'queue.lock',{'job':os.environ['SLURM_JOB_ID'],'identity':sha(folder/'Queue.json')})
    deadline=time.monotonic()+p['resource_request']['wall_seconds'];s['phase']='running';write(folder/'checkpoint.json',s)
    if resume and (folder/'Pause.json').exists():
        write(folder/('pause-ack-'+str(time.time_ns())+'.json'),read(folder/'Pause.json'));(folder/'Pause.json').unlink()
    normal=False
    try:
        while s['cursor']<len(p['rows']):
            row=p['rows'][s['cursor']];c=configuration.load(row['config']);state=batch.state(row)
            if can_advance(state):
                s['history'].append({'run_id':row['run_id'],'phase':'completed','source':'verified application state, not sbatch exit'});s['cursor']+=1;s.pop('active_child',None);write(folder/'checkpoint.json',s);continue
            if (folder/'Pause.json').exists() or time.monotonic()+c['resources']['drain_seconds']+c['provider']['total_timeout']>deadline:s['phase']='paused';break
            if state.get('requires_investigation') or state.get('unknown_sends',0) or state.get('writer_lock') or state['phase'] not in ('not_started','prepared','paused'):s['phase']='stopped';s['reason']='child active/failed/unknown; no replacement or budget reset';break
            action='resume' if state['phase']=='paused' else 'run';s['active_child']=row['run_id'];write(folder/'checkpoint.json',s)
            result=subprocess.run(batch.command(row,action,real=True),check=False)
            after=batch.state(row);s['history'].append({'run_id':row['run_id'],'exit_code':result.returncode,'phase':after['phase']});write(folder/'checkpoint.json',s)
            if result.returncode or not can_advance(after):s['phase']='paused' if after['phase']=='paused' else 'stopped';s['reason']='child not fully completed; stop finite queue';break
        else:s['phase']='completed'
        write(folder/'checkpoint.json',s);normal=True;return s
    finally:
        if normal and s['phase'] in ('completed','paused'):(folder/'queue.lock').unlink()


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['prepare','run','resume','pause','status','submit']);ap.add_argument('--queue',type=Path,required=True);ap.add_argument('--batch',type=Path);ap.add_argument('--items',nargs='+');ap.add_argument('--approve-total',type=int);ap.add_argument('--submit',action='store_true');a=ap.parse_args()
    if a.action=='prepare':result=prepare(a.batch,a.items,a.queue,a.approve_total)
    elif a.action=='pause':result=pause(a.queue)
    elif a.action=='status':result=read(a.queue/'checkpoint.json')
    elif a.action in ('run','resume'):result=work(a.queue,a.approve_total,a.action=='resume')
    else:
        p=read(a.queue/'Queue.json');s=read(a.queue/'checkpoint.json');operation='resume' if s['phase']=='paused' else 'run'
        if s['phase'] not in ('prepared','paused') or (a.queue/'queue.lock').exists():raise PermissionError('only original prepared/paused finite queue, no unknown owner')
        if a.approve_total!=p['total_original_request_cap']:raise PermissionError('explicit original ALL-run cap required')
        cmd=['sbatch','--parsable','--no-requeue','--nodes=1','--ntasks=1','--cpus-per-task=4','--mem=4096M','--time=12:00:00','--signal=B:USR1@1260','--partition=128C_02','--account=wz','--qos=normal','--chdir='+str(ROOT),'--output='+str(ROOT/'logs/queue-%j.out'),'--error='+str(ROOT/'logs/queue-%j.err'),str(ROOT/'experiments/triad/serial_queue.sbatch'),str(a.queue.resolve()),operation,str(a.approve_total)]
        result={'submitted':False,'command':cmd}
        if a.submit:
            for old in (a.queue/'submissions').glob('*.json'):
                receipt=read(old)
                if receipt['state']!='submitted':raise PermissionError('unknown prior queue submission; no resend or new segment')
                account=subprocess.run(['sacct','-n','-P','-j',receipt['job_id'],'--format=JobIDRaw,State'],check=True,text=True,capture_output=True)
                state=next((r.split('|')[1].split()[0] for r in account.stdout.splitlines() if r.split('|')[0]==receipt['job_id']),None)
                if state not in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED'}:raise PermissionError('prior queue segment active or accounting unknown')
            claims=a.queue/'submissions';claims.mkdir(exist_ok=True);claimfile=claims/(operation+'-'+sha(a.queue/'checkpoint.json')+'.json');record={'state':'submission_reserved','command':cmd,'automatic_retry':False};claim(claimfile,record)
            (ROOT/'logs').mkdir(exist_ok=True);answer=subprocess.run(cmd,check=True,text=True,capture_output=True);job=answer.stdout.strip().split(';')[0]
            if not job.isdigit():raise RuntimeError('unknown queue submission; no resend')
            record.update(state='submitted',job_id=job);write(claimfile,record);result=record
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result.get('phase')!='stopped' else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False}),file=sys.stderr);raise SystemExit(2)
