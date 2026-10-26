#!/usr/bin/env python3
"""Constructive TSP pilot; help/check/plan do not call API or solve."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
import argparse,json,os,shlex,signal,subprocess
from heuristic_design.core import execution
from heuristic_design.core.storage import read,write
from heuristic_design.problems.tsp import campaign as c
from heuristic_design.problems.tsp.operations import Adapter


def credential(path):
    if os.environ.get('LEAFAPI_API_KEY'):return
    if path is None:raise ValueError('LEAFAPI_API_KEY missing; supply existing --env-file')
    for line in Path(path).read_text().splitlines():
        text=line.strip()
        if text.startswith('export '):text=text[7:].strip()
        if text.startswith('LEAFAPI_API_KEY='):
            value=shlex.split(text.split('=',1)[1],comments=True)
            if len(value)!=1:raise ValueError('invalid credential assignment')
            os.environ['LEAFAPI_API_KEY']=value[0];return
    raise ValueError('credential absent; no value printed')


def main():
    p=argparse.ArgumentParser(description=__doc__);sp=p.add_subparsers(dest='command',required=True)
    for name in ['doctor','test']:sp.add_parser(name)
    for name in ['check','plan','prepare']:
        q=sp.add_parser(name);q.add_argument('--config',required=True)
        if name=='prepare':q.add_argument('--directory',required=True)
    for name in ['run','resume','status','summary','stop','_campaign']:
        q=sp.add_parser(name);q.add_argument('--directory',required=True)
        if name in ['run','resume','_campaign']:
            q.add_argument('--allow-api',action='store_true');q.add_argument('--env-file');q.add_argument('--background',action='store_true')
        if name=='summary':q.add_argument('--write',action='store_true')
    q=sp.add_parser('_work');q.add_argument('--run-dir',required=True)
    a=p.parse_args();signal.signal(signal.SIGHUP,signal.SIG_IGN)
    if a.command=='doctor':r={'python':sys.version.split()[0],'root':str(ROOT),'key_present':bool(os.environ.get('LEAFAPI_API_KEY')),'API':0,'solves':0}
    elif a.command=='test':
        import unittest
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_tsp_adapter.py')
        result=unittest.TextTestRunner(verbosity=2).run(suite);r={'passed':result.wasSuccessful(),'tests':result.testsRun,'real_API':0}
        if not result.wasSuccessful():raise SystemExit(2)
    elif a.command in ['check','plan']:
        config=c.load_config(a.config);r={'valid':True,'config':config,'API':0,'solves':0,'stages':{'H':10,'IND_701':10,'IND_702':10,'EVO_801':10,'EVO_802':10},'global_API_attempt_cap':75}
    elif a.command=='prepare':r=c.prepare(a.config,Path(a.directory))
    elif a.command=='_work':r=execution.work(Path(a.run_dir).resolve(),adapter=Adapter())
    else:
        directory=Path(a.directory).resolve()
        if a.command=='status':r={'state':read(directory/'Campaign_state.json'),'lock_present':(directory/'.campaign.lock').exists(),'source_identity':'matched' if c.check(directory) else None}
        elif a.command=='summary':r=c.summary(directory,write_files=a.write)
        elif a.command=='stop':r=c.stop(directory)
        else:
            config=c.check(directory)['config']
            if config['api_mode']=='real':
                if not a.allow_api or not config['real_requests_authorized']:raise PermissionError('real run requires --allow-api and bound authorization')
                credential(a.env_file)
            if a.background:
                args=[sys.executable,'-B',str(Path(__file__).resolve()),'_campaign','--directory',str(directory)]
                if a.allow_api:args.append('--allow-api')
                log=directory/'Console.log'
                with log.open('ab') as f:proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=f,stderr=f,cwd=ROOT,start_new_session=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
                write(directory/'Launch.json',{'pid':proc.pid,'operation':a.command,'log':str(log)});r={'pid':proc.pid,'log':str(log)}
            else:r=c.run(directory,allow_api=a.allow_api,resume=a.command=='resume' or a.command=='_campaign' and read(directory/'Campaign_state.json')['phase']=='paused')
    print(json.dumps(r,ensure_ascii=False,indent=2))
    if r.get('phase') in ('partial','stopped','expired'):raise SystemExit(2)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'error':str(exc),'automatic_retry':False}),file=sys.stderr);raise SystemExit(2)
