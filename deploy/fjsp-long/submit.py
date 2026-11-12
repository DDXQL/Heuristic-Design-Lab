#!/usr/bin/env python3
"""Build one sbatch invocation. Printing is default; --submit is user action."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]


def command(deployment,configuration,action,pause_after_attempts=None):
    from experiments.common.run_frozen import configuration as load
    d=json.loads(Path(deployment).read_text());document,c,run,pending=load(configuration)
    required={'version','remote_root','python','partition','account','qos','memory_mib','walltime_seconds','credential_file'}
    if set(d)!=required or d['version']!='fjsp-single-slurm-v1':raise ValueError('explicit deployment schema required')
    if pending or any(d[k] is None for k in ('remote_root','python','partition','memory_mib','walltime_seconds','credential_file')):
        raise ValueError('deployment/configuration is not frozen')
    x=c['execution_contract']
    if d['walltime_seconds']!=x['segment_seconds']:raise ValueError('Slurm walltime must match application segment')
    if type(d['memory_mib']) is not int or d['memory_mib']<=0:raise ValueError('explicit memory request required')
    if not Path(d['credential_file']).is_absolute():raise ValueError('explicit existing credential file path required')
    if action not in ('run','resume'):raise ValueError('single explicit action required')
    h,remainder=divmod(d['walltime_seconds'],3600);m,s=divmod(remainder,60)
    cmd=['sbatch','--parsable','--no-requeue','--nodes=1','--ntasks=1',
         '--cpus-per-task='+str(x['allocated_cpus']),'--mem='+str(d['memory_mib'])+'M',
         f'--time={h:02d}:{m:02d}:{s:02d}', '--signal=B:USR1@'+str(x['drain_seconds']),
         '--chdir='+d['remote_root'],'--output='+d['remote_root']+'/logs/fjsp-%j.out',
         '--error='+d['remote_root']+'/logs/fjsp-%j.err']
    for key in ('partition','account','qos'):
        if d[key]:cmd.append('--'+key+'='+d[key])
    cmd += [str(ROOT/'deploy/fjsp-long/cluster.sbatch'),action,str(Path(configuration).resolve()),d['python'],d['credential_file']]
    if pause_after_attempts is not None:
        if not 1<=pause_after_attempts<=c['api_attempt_cap']:raise ValueError('finite prefix exceeds original total budget')
        cmd.append(str(pause_after_attempts))
    return d,cmd


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','resume']);parser.add_argument('--deployment',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--submit',action='store_true')
    parser.add_argument('--pause-after-attempts',type=int)
    args=parser.parse_args()
    try:
        d,cmd=command(args.deployment,args.config,args.action,args.pause_after_attempts)
        if args.submit:
            if Path(d['remote_root']).resolve()!=ROOT:raise ValueError('submit only inside the frozen cluster release')
            from experiments.common.run_frozen import configuration
            from heuristic_design.core import evolution_v1 as engine
            from heuristic_design.core.storage import sha,write
            _,c,run,_=configuration(args.config)
            p,s=engine.check(run)
            if s['phase']!=('prepared' if args.action=='run' else 'paused') or (run/'.coordinator.lock').exists():
                raise ValueError('submission requires prepared or safely paused original checkpoint without writer lock')
            claims=run/'submissions';claims.mkdir(exist_ok=True)
            previous=[json.loads(path.read_text()) for path in claims.glob('*.json')]
            if any(row['state']!='submitted' for row in previous):raise ValueError('unknown prior submission; investigate, never resubmit')
            jobs=[row['job_id'].split(';')[0] for row in previous]
            if jobs:
                accounting=subprocess.run(['sacct','-n','-P','-j',','.join(jobs),'--format=JobIDRaw,State'],
                    check=True,text=True,capture_output=True)
                states={row.split('|')[0]:row.split('|')[1].split()[0] for row in accounting.stdout.splitlines() if '|' in row}
                terminal={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}
                if any(states.get(job) not in terminal for job in jobs):raise ValueError('prior job terminal accounting missing; no overlapping resume')
            claim=claims/(args.action+'-'+sha(run/'checkpoint.json')+'.json')
            fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            receipt={'state':'submission_reserved','automatic_resubmit':False,'command':cmd,
                     'configuration_sha256':sha(args.config),'deployment_sha256':sha(args.deployment)}
            with os.fdopen(fd,'w') as f:
                json.dump(receipt,f);f.flush();os.fsync(f.fileno())
            (ROOT/'logs').mkdir(exist_ok=True)
            result=subprocess.run(cmd,check=True,text=True,capture_output=True)
            job=result.stdout.strip()
            if not job.split(';')[0].isdigit():raise ValueError('uncertified sbatch receipt; investigate before resubmitting')
            write(claim,{**receipt,'state':'submitted','job_id':job})
            print(job)
        else:print(shlex.join(cmd))
        return 0
    except Exception as exc:print(type(exc).__name__+': '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
