#!/usr/bin/env python3
"""Mac upload and retrieval only; reuse the admitted SSH/install/export mechanisms."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from experiments.triad import cluster,launch_concurrent
from heuristic_design.core.storage import write

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['stage','fetch']);a=ap.parse_args()
    report=ROOT/'reports/native-continuation-20261115'/(a.action+'-'+str(time.time_ns()));report.mkdir(parents=True)
    with cluster.shared.Connection() as c:
        result=cluster.stage_release(c,report) if a.action=='stage' else launch_concurrent.fetch(c,'native-eoh-501-502',report)
    result.update(local_evidence=str(report),remote_root=cluster.REMOTE,local_API_requests=0,local_solves=0,Slurm_submitted=False)
    write(report/'status.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
