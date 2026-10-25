"""Synthetic-only launchd acceptance entry; never invokes the FJSP evaluator."""
import argparse
import json
from pathlib import Path
from fjsp_usage.long_jobs.local import create_toy,launch,work,observe,request_pause

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('toy-prepare','launch','work','status','pause'))
    p.add_argument('--job-dir',type=Path,required=True);p.add_argument('--delay',type=float,default=.4);p.add_argument('--crash',action='store_true')
    a=p.parse_args()
    if a.stage=='toy-prepare':create_toy(a.job_dir,a.delay,a.crash)
    elif a.stage=='launch':print(launch(a.job_dir))
    elif a.stage=='work':work(a.job_dir)
    elif a.stage=='status':print(json.dumps(observe(a.job_dir)))
    else:request_pause(a.job_dir,'explicit engineering pause request')

if __name__=='__main__':main()
