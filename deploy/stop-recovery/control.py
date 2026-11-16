#!/usr/bin/env python3
"""Manual R11 stage, audited handoff, bounded two-step continuation, query/fetch."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import write
from experiments.triad import cluster,launch_concurrent
REMOTE='/public2/home/qiuqian/hdl-deploy/triad-fjsp-stop-recovery-20261116-r11'
BUNDLE=Path('/Users/DDXQL/Developer/transfer-outbox/triad-fjsp-stop-recovery-20261116-r11.zip')
RELATIVE='plans/stop-recovery-501-502/Shared.json'


def invoke(c,script,args):return json.loads(c.run([cluster.shared.PY,'-s','-B',REMOTE+'/experiments/triad/'+script,*args]).stdout)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['stage','finite-submit','status','certify','continue','fetch'])
    ap.add_argument('--submit',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-requests',type=int);ap.add_argument('--approve-new-requests',type=int);ap.add_argument('--approve-new-solves',type=int);ap.add_argument('--acknowledge-known-failures-keep-budget',action='store_true');a=ap.parse_args()
    if a.action in ('finite-submit','continue') and not(a.submit and a.allow_api and a.allow_solves and a.approve_requests==2040):raise PermissionError('manual submission requires API/solve/original2040 approval')
    if a.action=='finite-submit' and not(a.acknowledge_known_failures_keep_budget and a.approve_new_requests==2 and a.approve_new_solves==84):raise PermissionError('finite step requires explicit audited failed-slot acknowledgment, at most2 new requests/84 inclusive solves')
    report=ROOT/'reports/stop-recovery-20261116'/(a.action+'-'+str(time.time_ns()));report.mkdir(parents=True)
    result={'action':a.action,'remote_root':REMOTE,'local_evidence':str(report),'local_API_requests':0,'local_solves':0,'automatic_retry':False}
    try:
        with cluster.shared.Connection() as c:
            if a.action=='stage':
                cluster.REMOTE=REMOTE;cluster.BUNDLE=BUNDLE;result.update(cluster.stage_release(c,report))
                prepared=invoke(c,'stop_recovery.py',['prepare']);write(report/'prepared.json',prepared);result.update(prepared,account_lease_changed=False,Slurm_submitted=False)
            elif a.action=='finite-submit':
                handoff=invoke(c,'stop_recovery.py',['activate','--acknowledge-known-failures-keep-budget']);write(report/'handoff.json',handoff)
                result.update(invoke(c,'stop_recovery.py',['finite-submit','--submit','--allow-api','--allow-solves','--approve-requests','2040','--approve-new-requests','2','--approve-new-solves','84']))
            elif a.action=='status':result.update(invoke(c,'parallel.py',['status','--manifest',REMOTE+'/'+RELATIVE]))
            elif a.action=='certify':result.update(invoke(c,'stop_recovery.py',['certify']))
            elif a.action=='continue':result.update(invoke(c,'parallel.py',['resume','--manifest',REMOTE+'/'+RELATIVE,'--submit','--allow-api','--allow-solves','--approve-requests','2040']))
            else:
                launch_concurrent.REMOTE=REMOTE;result.update(launch_concurrent.fetch(c,'stop-recovery-501-502',report))
        write(report/'status.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as e:
        result.update(error_type=type(e).__name__,error=str(e));write(report/'status.json',result);print(json.dumps(result,ensure_ascii=False,indent=2),file=sys.stderr);raise SystemExit(2)

if __name__=='__main__':main()
