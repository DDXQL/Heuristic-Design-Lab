#!/usr/bin/env python3
"""User-invoked one-job submission only. Never starts a formal search."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
os.environ['PYTHONNOUSERSITE']='1'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
for _name in list(os.environ):
    if any(token in _name.upper() for token in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN','SECRET')):
        os.environ.pop(_name,None)
ROOT=Path(__file__).resolve().parents[2]


def command(partition):
    if not partition or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in partition):
        raise ValueError('explicit safe partition name required')
    return ['sbatch','--parsable','--no-requeue','--partition='+partition,
            '--chdir='+str(ROOT),'--output='+str(ROOT/'logs/mock-%j.out'),
            '--error='+str(ROOT/'logs/mock-%j.err'),str(ROOT/'deploy/cluster-mock/mock.sbatch')]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partition',required=True);parser.add_argument('--submit',action='store_true')
    args=parser.parse_args();cmd=command(args.partition)
    if not args.submit:print(shlex.join(cmd));return
    # Lightweight import/manifest check only on login; all Mock compute is sbatch.
    subprocess.run([sys.executable,'-B',str(ROOT/'deploy/cluster-mock/accept.py'),'check'],check=True)
    up=subprocess.run(['sinfo','-h','-p',args.partition,'-o','%a'],check=True,text=True,capture_output=True)
    if 'up' not in up.stdout.lower().split():raise ValueError('selected partition not currently UP/available')
    claim=ROOT/'mock-submission.json'
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump({'state':'submission_reserved','command':cmd,'automatic_retry':False},f);f.flush();os.fsync(f.fileno())
    (ROOT/'logs').mkdir(exist_ok=True)
    result=subprocess.run(cmd,check=True,text=True,capture_output=True)
    job=result.stdout.strip()
    if not job.split(';')[0].isdigit():raise ValueError('unknown sbatch receipt: preserve claim; never resubmit automatically')
    record={'state':'submitted','job_id':job.split(';')[0],'command':cmd,'automatic_retry':False}
    tmp=claim.with_suffix('.tmp');tmp.write_text(json.dumps(record,indent=2)+'\n');tmp.replace(claim)
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as error:print(type(error).__name__+': '+str(error),file=sys.stderr);raise SystemExit(2)
