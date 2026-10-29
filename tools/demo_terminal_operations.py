"""T09 demonstration using actual CLI subprocesses; never enables real API."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write
from heuristic_design.core.terminal_ops import settings


def demo(root,report):
    root=Path(root).resolve();report=Path(report).resolve()
    if root.exists():raise ValueError('new demo run root required')
    root.mkdir(parents=True);report.mkdir(parents=True,exist_ok=True)
    records=[]
    def command(problem,action,*args,expected=0):
        cmd=[sys.executable,'-B',str(ROOT/'experiments/common/manage.py'),'--problem',problem,action,*map(str,args)]
        p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=90)
        index=len(records)
        (report/f'{index:02d}-{problem}-{action}.stdout.log').write_text(p.stdout)
        (report/f'{index:02d}-{problem}-{action}.stderr.log').write_text(p.stderr)
        records.append({'argv':cmd,'exitcode':p.returncode,'expected':expected})
        if p.returncode!=expected:raise AssertionError(p.stderr)
        return p
    command('fjsp','doctor')
    config=ROOT/'experiments/common/configs/terminal-demo.mock.json'
    command('fjsp','preview','--config',config)
    run=root/'mock'
    command('fjsp','prepare','--config',config,'--run-dir',run)
    cmd=[sys.executable,'-B',str(ROOT/'experiments/common/manage.py'),'--problem','fjsp','run','--run-dir',str(run)]
    with (report/'mock-start.log').open('w') as log:
        worker=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+30
            while read(run/'checkpoint.json')['completed_tasks']<6:
                if worker.poll() is not None:raise AssertionError('run ended before live pause')
                if time.monotonic()>deadline:raise TimeoutError('demo start deadline')
                time.sleep(.05)
            live=json.loads(command('fjsp','status','--run-dir',run).stdout)
            command('fjsp','pause','--run-dir',run,'--wait','--wait-seconds','30')
            worker.wait(timeout=30)
            assert worker.returncode==0
        finally:
            if worker.poll() is None:
                worker.terminate();worker.wait(timeout=30)
    paused=json.loads(command('fjsp','status','--run-dir',run).stdout)
    assert paused['phase']=='paused'
    command('fjsp','resume','--run-dir',run)
    final=json.loads(command('fjsp','status','--run-dir',run).stdout)
    command('fjsp','export','--run-dir',run,'--output',report/'mock-exports')
    assert final['phase']=='completed' and final['generation_requests']==30
    for problem in ('fjsp','tsp'):
        fixed=root/(problem+'-fixed')
        command(problem,'doctor','--config',ROOT/f'experiments/common/configs/{problem}-fixed-development.json')
        command(problem,'prepare','--config',ROOT/f'experiments/common/configs/{problem}-fixed-development.json','--run-dir',fixed)
        command(problem,'run','--run-dir',fixed)
        command(problem,'status','--run-dir',fixed)
        command(problem,'export','--run-dir',fixed,'--output',report/(problem+'-fixed-exports'))
    c=settings(ROOT/'experiments/common/configs/fjsp-real.template.json')
    c['data_manifest']=str(ROOT/'experiments/common/fixtures/fjsp-development-manifest.json')
    assert c['real_requests_authorized'] is False
    guard=root/'real-guard.config.json';write(guard,c)
    command('fjsp','doctor','--config',guard)
    command('fjsp','preview','--config',guard)
    command('fjsp','prepare','--config',guard,'--run-dir',root/'real-blocked')
    command('fjsp','run','--run-dir',root/'real-blocked',expected=2)
    command('fjsp','run','--run-dir',root/'real-blocked','--allow-api',expected=2)
    summary={'actual_network_API_calls':0,'label':'Mock CLI plus handwritten fixed synthetic solves; no real search',
             'live':live,'paused':paused,'completed':final,'commands':records,
             'real_guard_checkpoint_phase':read(root/'real-blocked/checkpoint.json')['phase']}
    write(report/'demo.json',summary)
    print(json.dumps({'steps':len(records),'paused':paused['phase'],'final':final['phase'],'real_API_calls':0},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-root',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();demo(args.run_root,args.report)
