#!/usr/bin/env python3
"""Explicit user submission of one new acceptance job; no retries."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
for name in list(os.environ):
    if any(x in name.upper() for x in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN','SECRET')):os.environ.pop(name,None)
os.environ['PYTHONNOUSERSITE']='1';os.environ['PYTHONDONTWRITEBYTECODE']='1'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partition',default='128C_02');parser.add_argument('--submit',action='store_true')
    parser.add_argument('--approve-solves',type=int)
    args=parser.parse_args()
    if not args.partition or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.partition):raise ValueError('invalid partition')
    plan=json.loads((ROOT/'deploy/solve-check/plan.json').read_text());r=plan['resources']
    hours,left=divmod(r['Slurm_seconds'],3600);minutes,seconds=divmod(left,60)
    cmd=['sbatch','--parsable','--no-requeue','--partition='+args.partition,'--chdir='+str(ROOT),
         '--cpus-per-task='+str(r['cpus']),'--mem='+str(r['memory_mib'])+'M',
         '--time='+f'{hours:02d}:{minutes:02d}:{seconds:02d}',
         '--output='+str(ROOT/'logs/solve-%j.out'),'--error='+str(ROOT/'logs/solve-%j.err'),str(ROOT/'deploy/solve-check/solve.sbatch')]
    if not args.submit:print(shlex.join(cmd));return
    if args.approve_solves!=16:raise PermissionError('user must explicitly approve the inclusive 16-solve cap')
    subprocess.run([sys.executable,'-s','-B',str(ROOT/'deploy/solve-check/accept.py'),'check'],check=True)
    up=subprocess.run(['sinfo','-h','-p',args.partition,'-o','%a'],check=True,text=True,capture_output=True)
    if 'up' not in up.stdout.lower().split():raise ValueError('partition not UP')
    claim=ROOT/'solve-submission.json'
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'state':'submission_reserved','command':cmd,'max_solves':16},f);f.flush();os.fsync(f.fileno())
    (ROOT/'logs').mkdir(exist_ok=True)
    result=subprocess.run(cmd,check=True,text=True,capture_output=True)
    job=result.stdout.strip().split(';')[0]
    if not job.isdigit():raise ValueError('unknown sbatch receipt; preserve reservation, no resubmit')
    tmp=claim.with_suffix('.tmp');tmp.write_text(json.dumps({'state':'submitted','job_id':job,'command':cmd,'max_solves':16},indent=2)+'\n');tmp.replace(claim)
    print(json.dumps({'state':'submitted','job_id':job,'max_solves':16,'API_requests':0},indent=2))


if __name__=='__main__':
    try:main()
    except Exception as error:print(type(error).__name__+': '+str(error),file=sys.stderr);raise SystemExit(2)
