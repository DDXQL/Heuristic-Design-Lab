#!/usr/bin/env python3
"""Mac-only retrieval compatibility adapter. No frozen remote source changes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from experiments.triad import launch_concurrent as original
from heuristic_design.core.storage import write


class SettledConnection:
    """A controller can forget terminal job IDs while sacct retains them.

    Query the complete current-user queue with the admitted existing mechanism,
    then filter exactly the requested job. A failed queue query still raises;
    never turn an arbitrary SSH/scheduler error into an empty queue. The original
    fetch still requires that exact job's terminal sacct record before export.
    """
    def __init__(self,inner):self.inner=inner
    def run(self,args,source=None,check=True):
        if args and args[0]=='squeue' and '-j' in args:
            job=args[args.index('-j')+1]
            if not job.isdigit():raise ValueError('numeric original job ID required')
            result=self.inner.run(['squeue','-h','-u','qiuqian','-o','%i|%T'],check=True)
            selected=[line for line in result.stdout.splitlines() if line.split('|')[0].strip()==job]
            return subprocess.CompletedProcess(args,result.returncode,stdout='\n'.join(selected)+('\n' if selected else ''),stderr=result.stderr)
        return self.inner.run(args,source,check=check)
    def copy(self,*args,**kwargs):return self.inner.copy(*args,**kwargs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',choices=[original.REAL,original.MOCK],default=original.REAL)
    a=parser.parse_args()
    out=original.REPORT/('settled-fetch-'+str(time.time_ns()));out.mkdir(parents=True)
    status={'action':'fetch','compatibility_adapter':'queue-by-user, exact sacct terminal check retained','remote_root':original.REMOTE,'local_evidence':str(out),'API_requests':0,'actual_solves':0,'Slurm_submitted':False,'frozen_sources_modified':False,'retrieved':False}
    try:
        with original.cluster.shared.Connection() as connection:
            status.update(original.fetch(SettledConnection(connection),a.batch,out))
        for member in status['members']:
            seed=501 if '501' in member['中文名称'] else 502 if '502' in member['中文名称'] else 503
            member['中文名称']=('FJSP单规则EoH：第'+str(seed-500)+'次独立搜索' if a.batch==original.REAL else '双Slurm无API工程检查')+'（种子'+str(seed)+'）'
        write(out/'status.json',status);print(json.dumps(status,ensure_ascii=False,indent=2));return 0
    except Exception as error:
        status.update(error_type=type(error).__name__,error=str(error),automatic_retry=False)
        write(out/'status.json',status);print(json.dumps(status,ensure_ascii=False,indent=2),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
