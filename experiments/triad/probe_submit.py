#!/usr/bin/env python3
"""Cluster-side manual two-job submission; durable receipts, no resubmit/retry."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad.concurrency_probe import claim,collect
PY='/public2/home/qiuqian/hdl-envs/portable-v2/bin/python'
RUN=ROOT/'runs/cluster-api-concurrency-20261114'


def command(spec,folder,role):
    r=spec['resources'];return ['sbatch','--parsable','--no-requeue','--nodes=1','--ntasks=1','--cpus-per-task=1','--mem='+str(r['memory_mib_per_job'])+'M','--time=00:30:00','--partition='+r['partition'],'--account='+r['account'],'--qos='+r['qos'],'--chdir='+str(ROOT),'--job-name=hdl-probe-'+str(spec['phase'])+'-'+str(role),'--output='+str(ROOT/'logs'/f'probe-{spec["phase"]}-{role}-%j.out'),'--error='+str(ROOT/'logs'/f'probe-{spec["phase"]}-{role}-%j.err'),str(ROOT/'experiments/triad/probe.sbatch'),str(folder),str(role),PY]


def submit(phase,approve,exclusive_hours,confirmed,send=False):
    original=ROOT/'preparations/cluster-concurrency-20261114/phase1';spec=read(original/'Probe.pending.json');spec=copy.deepcopy(spec);spec.update(phase=phase,global_API_width=phase)
    folder=RUN/f'phase{phase}'
    if phase not in (1,2):raise ValueError('only the bounded 4+4 plan exists')
    if phase==2:
        first=collect(RUN/'phase1')
        if not first['passed']:raise PermissionError('stage1 must pass; API2 never starts automatically')
        spec['phase1_pass_sha256']=sha(RUN/'phase1/PASS.json')
    commands=[command(spec,folder,r) for r in (0,1)]
    if not send:return {'submitted':False,'commands':commands,'physical_send_cap':4,'real_API_requests':0,'solver_calls':0}
    if approve!=4 or not confirmed or exclusive_hours is None or not 1<=exclusive_hours<=72:raise PermissionError('manual --approve-sends 4 and fresh explicit all-device exclusion duration required')
    if folder.exists():raise FileExistsError('phase already prepared/reserved/submitted; inspect original receipts, never resubmit')
    folder.mkdir(parents=True);write(folder/'Probe.json',spec)
    for item in spec['prompts']:shutil.copyfile(original/item['path'],folder/item['path'])
    write(folder/'Approval.json',{'approved_physical_sends':4,'probe_sha256':sha(folder/'Probe.json'),'confirm_all_devices_exclusive':True,'exclusive_until':time.time()+exclusive_hours*3600,'approved_at':time.time(),'scope':'only engineering stage '+str(phase)+'; solver0; no research budget use'})
    claim(Path(spec['account_gate'])/'generation.lock',{'protocol':'PROBE:'+sha(folder/'Probe.json'),'run_id':folder.name,'scope':'engineering batch; two internal jobs share request gate; production generation excluded'})
    (ROOT/'logs').mkdir(exist_ok=True)
    receipts=[]
    for role,cmd in enumerate(commands):
        record={'role':role,'phase':phase,'state':'submission_reserved','command':cmd,'physical_send_cap_for_role':2,'automatic_retry':False}
        path=folder/'submissions'/f'role-{role}.json';claim(path,record)
        answer=subprocess.run(cmd,check=True,text=True,capture_output=True);job=answer.stdout.strip().split(';')[0]
        if not job.isdigit():raise RuntimeError('unknown submission; keep both phase claims, no resend')
        record.update(state='submitted',job_id=job);write(path,record);receipts.append(record)
    return {'submitted':True,'phase':phase,'receipts':receipts,'phase_send_cap':4,'global_API_width':phase,'solver_calls':0,'Mac_required_after_submission':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['submit','status']);ap.add_argument('--phase',type=int,default=1);ap.add_argument('--submit',action='store_true');ap.add_argument('--approve-sends',type=int);ap.add_argument('--exclusive-hours',type=float);ap.add_argument('--confirm-exclusive-account',action='store_true');a=ap.parse_args()
    print(json.dumps(submit(a.phase,a.approve_sends,a.exclusive_hours,a.confirm_exclusive_account,a.submit) if a.action=='submit' else collect(RUN/f'phase{a.phase}'),ensure_ascii=False,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False}),file=sys.stderr);raise SystemExit(2)
