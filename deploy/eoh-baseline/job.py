#!/usr/bin/env python3
"""Manual single-job submission, using frozen executor; unknown receipts never resubmit."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'deploy/eoh-baseline'),str(ROOT/'code'),str(ROOT)]
import eoh_gap as e
from heuristic_design.core import execution
RUN=ROOT/'runs/fjsp-eoh-J-baseline-20261113-r1'
for n in list(os.environ):
    if any(x in n.upper() for x in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN','SECRET')):os.environ.pop(n,None)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['prepare','submit','resume'])
    ap.add_argument('--config',type=Path,default=ROOT/'deploy/eoh-baseline/research.pending.json')
    ap.add_argument('--submit',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--approve-budget',type=int)
    a=ap.parse_args();adapter=e.Adapter()
    if a.action=='resume':
        p=adapter.check_run(RUN);c=p['config'];_,s=e.protocol_state(RUN)
        execution.ledger(RUN,s,p,adapter=adapter)
        if s['phase']!='paused' or (RUN/'.execution.lock').exists() or (RUN/'Stop.json').exists():raise ValueError('only safely paused settled run can resume; never clear locks')
        if time.time()>=e.read(RUN/'Run_clock.json')['deadline']:raise ValueError('original deadline expired; never extend')
        claim=ROOT/'submissions'/f'resume-{s["cursor"]:06d}-{execution.pause_sequence(RUN,adapter=adapter):04d}.json'
    else:
        c,_,_,_,todo=e.preflight(a.config)
        if todo:raise PermissionError('PROTOCOL_UNFROZEN: '+', '.join(todo))
        if c['api_mode']!='real':raise PermissionError('this Slurm entry is the real EoH baseline, no Mock research claim')
        claim=ROOT/'submissions/initial.json'
    if a.action=='prepare':
        # Local/login-node file-only plan: no real run, no key, no dispatch, no submission.
        print(json.dumps(e.check(a.config),ensure_ascii=False,indent=2));return 0
    e.authorize(c,a.approve_budget,a.allow_api,original_deadline=e.read(RUN/'Run_clock.json')['deadline'] if a.action=='resume' else None)
    r=c['resources'];h,left=divmod(r['walltime_seconds'],3600);m,s=divmod(left,60)
    cmd=['sbatch','--parsable','--no-requeue','--partition='+r['partition'],'--chdir='+str(ROOT),'--nodes=1','--ntasks=1',
      '--cpus-per-task='+str(r['cpus']),'--mem='+str(r['memory_mib'])+'M','--time='+f'{h:02d}:{m:02d}:{s:02d}',
      '--output='+str(ROOT/'logs/eoh-%j.out'),'--error='+str(ROOT/'logs/eoh-%j.err')]
    for k in ('account','qos'):
        if r[k]:cmd.append('--'+k+'='+r[k])
    cmd += [str(ROOT/'deploy/eoh-baseline/eoh.sbatch'),'resume' if a.action=='resume' else 'run',str(c['api_attempt_cap'])]
    if not a.submit:print(json.dumps({'command':cmd,'submitted':False,'API_requests':0},ensure_ascii=False,indent=2));return 0
    up=subprocess.run(['sinfo','-h','-p',r['partition'],'-o','%a'],check=True,text=True,capture_output=True)
    if 'up' not in up.stdout.lower().split():raise ValueError('partition not UP; no submission')
    if a.action=='submit':
        if RUN.exists():
            p=adapter.check_run(RUN);_,s=e.protocol_state(RUN)
            if s['phase']!='prepared' or any(p['config'].get(k)!=v for k,v in c.items() if k!='real_requests_authorized'):raise ValueError('existing run is not the identical prepared protocol')
        else:e.prepare(RUN,a.config,approve_budget=a.approve_budget,allow_api=a.allow_api)
    (ROOT/'logs').mkdir(exist_ok=True);claim.parent.mkdir(exist_ok=True)
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    record={'state':'submission_reserved','operation':a.action,'command':cmd,'original_request_cap':c['api_attempt_cap'],'protocol_sha256':e.sha(RUN/'Protocol.json')}
    with os.fdopen(fd,'w') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
    value=subprocess.run(cmd,check=True,text=True,capture_output=True)
    job=value.stdout.strip().split(';')[0]
    if not job.isdigit():raise ValueError('unknown sbatch receipt; retain reservation, no resend')
    record.update(state='submitted',job_id=job);e.write(claim,record);e.write(ROOT/'latest-submission.json',record)
    print(json.dumps(record,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as x:print(json.dumps({'error_type':type(x).__name__,'error':str(x),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
