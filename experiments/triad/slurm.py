#!/usr/bin/env python3
"""One independent experiment segment. Dry command generation is the default."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import batch,runtime,configuration


def command(row,action,python):
    c=configuration.load(row['config']);r=c['resources'];todo=configuration.gaps(c)
    if todo or r['partition'] is None:raise PermissionError('PROTOCOL_PENDING: '+', '.join(todo+(['resources.partition'] if r['partition'] is None else [])))
    h,left=divmod(r['segment_seconds'],3600);m,s=divmod(left,60)
    cmd=['sbatch','--parsable','--no-requeue','--nodes=1','--ntasks=1','--cpus-per-task='+str(r['cpus']),'--mem='+str(r['memory_mib'])+'M','--time='+f'{h:02d}:{m:02d}:{s:02d}',
      '--partition='+r['partition'],'--signal=B:USR1@'+str(r['drain_seconds']),'--chdir='+str(ROOT),'--job-name='+row['run_id'],
      '--comment='+row['run_id']+':'+row['child_config_sha256'],
      '--output='+str(ROOT/'logs'/ (row['run_id']+'-%j.out')),'--error='+str(ROOT/'logs'/(row['run_id']+'-%j.err'))]
    for k in ('account','qos'):
        if r[k]:cmd+=['--'+k+'='+r[k]]
    cmd += [str(ROOT/'experiments/triad/cluster.sbatch'),action,row['config'],row['run_dir'],python,str(c['api_attempt_cap'])]
    return cmd


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['run','resume']);ap.add_argument('--batch',type=Path,default=ROOT/'plans/triad-20261113');ap.add_argument('--experiment',required=True,choices=configuration.GROUPS);ap.add_argument('--seed',type=int,required=True)
    ap.add_argument('--python',default='/public2/home/qiuqian/hdl-envs/portable-v2/bin/python');ap.add_argument('--submit',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-budget',type=int)
    a=ap.parse_args();p=read(a.batch/'Batch.json');row=batch.select(p,a.experiment,a.seed)[0];cmd=command(row,a.action,a.python)
    if not a.submit:print(json.dumps({'submitted':False,'command':cmd},indent=2));return 0
    c=configuration.load(row['config'])
    if not a.allow_api or not a.allow_solves or a.approve_budget!=c['api_attempt_cap']:raise PermissionError('manual submit requires API/solve approval and ORIGINAL request cap')
    # Existing/unknown submissions anywhere in this batch prevent overlap.
    for other in p['rows']:
        if not other.get('run_dir'):continue
        claims=Path(other['run_dir'])/'submissions'
        for f in claims.glob('*.json'):
            receipt=read(f)
            if receipt['state']!='submitted':raise ValueError('unknown submission retained; no resend or next seed')
            job=receipt['job_id']
            account=subprocess.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State'],check=True,text=True,capture_output=True)
            state=next((r.split('|')[1].split()[0] for r in account.stdout.splitlines() if r.split('|')[0]==job),None)
            if state not in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}:raise ValueError('previous job active or accounting uncertain')
        info=batch.state(other)
        if info.get('requires_investigation') or info.get('unknown_sends',0) or info.get('writer_lock'):raise ValueError('active/unknown run blocks next submission')
    info=batch.state(row);d=Path(row['run_dir'])
    if a.action=='run' and info['phase']=='not_started':
        subprocess.run(batch.command(row,'prepare',real=True),check=True)
        info=batch.state(row)
    if info['phase']!=('prepared' if a.action=='run' else 'paused'):raise ValueError('run needs prepared, resume needs safely paused original run')
    claims=d/'submissions';claims.mkdir(exist_ok=True);claim=claims/(a.action+'-'+sha(d/'checkpoint.json')+'.json')
    record={'state':'submission_reserved','run_id':row['run_id'],'command':cmd,'original_cap':c['api_attempt_cap'],'automatic_retry':False}
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
    (ROOT/'logs').mkdir(exist_ok=True)
    result=subprocess.run(cmd,check=True,text=True,capture_output=True);job=result.stdout.strip().split(';')[0]
    if not job.isdigit():raise ValueError('unknown submission receipt; reserved claim preserved')
    record.update(state='submitted',job_id=job);write(claim,record);write(d/'latest-submission.json',record)
    print(json.dumps(record,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as x:print(json.dumps({'error_type':type(x).__name__,'error':str(x),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
