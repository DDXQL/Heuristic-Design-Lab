#!/usr/bin/env python3
"""Mac upload/inspection/query/retrieval using the already admitted SSH mechanism."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid
import zipfile
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('admitted_cluster',ROOT/'deploy/cluster-mock/control.py');shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import configuration,batch
REMOTE='/public2/home/qiuqian/hdl-deploy/triad-six-groups-20261113-r1'
BUNDLE=Path('/Users/DDXQL/Developer/transfer-outbox/triad-six-groups-prepared-20261113-r1.zip')
EXPORT='''import hashlib,json,pathlib,sys,time,zipfile
root=pathlib.Path(sys.argv[1]);run=pathlib.Path(sys.argv[2]);job=sys.argv[3]
if not run.resolve().is_relative_to((root/'runs').resolve()) or not job.isdigit():raise SystemExit('invalid retrieval identity')
s=json.loads((run/'checkpoint.json').read_text())
if s['phase'] in ('running','launching'):raise SystemExit('run not settled')
out=root/'exports'/('result-'+job+'-'+str(time.time_ns())+'.zip');out.parent.mkdir(exist_ok=True)
paths=[p for p in run.rglob('*') if p.is_file() and not p.is_symlink()]
paths += list((root/'logs').glob(run.name+'-'+job+'.*'))
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for n in files:z.write(root/n,n)
 z.writestr('retrieval-manifest.json',json.dumps({'files':files,'job_id':job,'run_id':run.name,'phase':s['phase']}))
print(json.dumps({'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'phase':s['phase']}))
'''
SAVE='''import pathlib,sys,base64,hashlib
p=pathlib.Path(sys.argv[1]);raw=base64.b64decode(sys.argv[2]);p.parent.mkdir(parents=True,exist_ok=True)
if p.exists() and p.read_bytes()!=raw:raise SystemExit('configuration already exists with different content; preserved')
if not p.exists():
 with p.open('xb') as f:f.write(raw)
print(hashlib.sha256(p.read_bytes()).hexdigest())
'''


def remote_path(path):
    p=Path(path).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('asset must be staged under the prepared project root first: '+str(p))
    return REMOTE+'/'+str(p.relative_to(ROOT))


def sync_config(connection,campaign,report):
    source=Path(campaign).resolve();doc=read(source);digest=sha(source);folder=REMOTE+'/configurations/'+digest
    for group in doc['groups']:
        path=(source.parent/group['config']).resolve();c=configuration.load(path)
        for k in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results'):
            if c.get(k):c[k]=remote_path(c[k])
        if isinstance(c['state_delivery'],dict):c['state_delivery']['file']=remote_path(c['state_delivery']['file'])
        # Credentials are referenced, NEVER copied. Account authority must be a cluster path.
        if c.get('account_gate') and not c['account_gate'].startswith('/public2/home/qiuqian/'):raise ValueError('cluster account gate must be explicitly configured; Mac gate is untouched')
        target=folder+'/'+c['group']+'.json';raw=json.dumps(c,ensure_ascii=False,indent=2).encode();connection.run([shared.PY,'-s','-B','-c',SAVE,target,base64.b64encode(raw).decode()]);group['config']=target
    doc['run_root']=REMOTE+'/runs/'+doc['campaign_id'];target=folder+'/campaign.json'
    raw=json.dumps(doc,ensure_ascii=False,indent=2).encode();connection.run([shared.PY,'-s','-B','-c',SAVE,target,base64.b64encode(raw).decode()])
    result=connection.run([shared.PY,'-s','-B',REMOTE+'/experiments/triad/batch.py','prepare','--campaign',target,'--batch',REMOTE+'/plans/'+doc['campaign_id']])
    (report/'remote-batch.json').write_text(result.stdout);return {'remote_campaign':target,'remote_batch':REMOTE+'/plans/'+doc['campaign_id']}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['inspect','stage','prepare','submit','resume','query','pause','fetch','summary'])
    ap.add_argument('--campaign',type=Path,default=ROOT/'experiments/triad/campaign.pending.json');ap.add_argument('--batch-name',default='triad-20261113');ap.add_argument('--experiment',choices=configuration.GROUPS);ap.add_argument('--seed',type=int)
    ap.add_argument('--submit',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-budget',type=int)
    a=ap.parse_args()
    if a.action in ('submit','resume') and (not a.submit or not a.allow_api or not a.allow_solves or type(a.approve_budget) is not int):raise PermissionError('manual submission requires explicit API/solve/original-budget approval')
    if a.action in ('submit','resume','query','pause','fetch') and (a.experiment is None or a.seed is None):raise ValueError('explicit experiment and seed required')
    if any(x not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for x in a.batch_name):raise ValueError('unsafe batch name')
    d=ROOT/'reports/triad-package-20261113'/(a.action+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);d.mkdir(parents=True)
    value={'action':a.action,'local_evidence':str(d),'remote_root':REMOTE,'local_API_requests':0,'local_solves':0,'new_compute_verification':False}
    try:
        with shared.Connection() as c:
            if a.action=='inspect':
                r=c.run(['/usr/bin/python3','-s','-'],(ROOT/'deploy/cluster-mock/inspect_remote.py').read_text());(d/'read-only-environment.json').write_text(r.stdout);value['inspection']=json.loads(r.stdout)
            elif a.action=='stage':
                expected=BUNDLE.with_suffix('.zip.sha256').read_text().split()[0]
                if sha(BUNDLE)!=expected:raise ValueError('local package hash mismatch')
                incoming='/public2/home/qiuqian/hdl-deploy/triad-incoming-20261113';c.run(['mkdir','-p',incoming]);target=incoming+'/'+BUNDLE.name;exists=c.run(['test','-e',target],check=False)
                if exists.returncode==1:c.copy(str(BUNDLE),shared.HOST+':'+target);c.copy(str(BUNDLE.with_suffix('.zip.sha256')),shared.HOST+':'+target+'.sha256')
                elif exists.returncode or c.run(['sha256sum',target]).stdout.split()[0]!=expected:raise ValueError('remote archive differs; preserved')
                installed=c.run([shared.PY,'-s','-B','-c',shared.INSTALL,target,REMOTE,expected]);(d/'release-verification.json').write_text(installed.stdout)
                checked=c.run([shared.PY,'-s','-B',REMOTE+'/experiments/triad/batch.py','plan']);(d/'login-plan.json').write_text(checked.stdout)
                value.update(uploaded=True,remote_manifest_verified=True,login_import_verified=True,formal_search_authorized=False)
            elif a.action=='prepare':value.update(sync_config(c,a.campaign,d))
            elif a.action=='summary':
                r=c.run([shared.PY,'-s','-B',REMOTE+'/experiments/triad/batch.py','summary','--batch',REMOTE+'/plans/'+a.batch_name]);(d/'batch-summary.json').write_text(r.stdout);value['summary_retrieved']=True
            elif a.action in ('submit','resume'):
                cmd=[shared.PY,'-s','-B',REMOTE+'/experiments/triad/slurm.py','run' if a.action=='submit' else 'resume','--batch',REMOTE+'/plans/'+a.batch_name,'--experiment',a.experiment,'--seed',str(a.seed),'--submit','--allow-api','--allow-solves','--approve-budget',str(a.approve_budget)]
                r=c.run(cmd);(d/'submission.json').write_text(r.stdout);value['receipt']=json.loads(r.stdout)
            else:
                remote_batch=json.loads(c.run(['cat',REMOTE+'/plans/'+a.batch_name+'/Batch.json']).stdout);row=batch.select(remote_batch,a.experiment,a.seed)[0]
                if a.action=='pause':
                    r=c.run([shared.PY,'-s','-B',REMOTE+'/experiments/triad/entry.py','pause','--config',row['config'],'--run-dir',row['run_dir']]);(d/'pause.json').write_text(r.stdout);value['pause_requested']=True
                else:
                    submission=json.loads(c.run(['cat',row['run_dir']+'/latest-submission.json']).stdout);job=submission.get('job_id','')
                    if submission['state']!='submitted' or not job.isdigit():raise ValueError('unknown job receipt; never resubmit')
                    queue=c.run(['squeue','-h','-j',job,'-o','%i|%T|%C']);account=c.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode,Elapsed,AllocCPUS,MaxRSS,NodeList'])
                    (d/'squeue.txt').write_text(queue.stdout);(d/'sacct.psv').write_text(account.stdout)
                    record=next((r.split('|') for r in account.stdout.splitlines() if r.split('|')[0]==job),None)
                    value.update(job_id=job,active=bool(queue.stdout.strip()),Slurm_state=record[1].split()[0] if record else None,exit_code=record[2] if record else None)
                    if a.action=='fetch':
                        if value['active'] or value['Slurm_state'] not in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}:raise ValueError('terminal accounting missing; wait before retrieval')
                        receipt=json.loads(c.run([shared.PY,'-s','-B','-c',EXPORT,REMOTE,row['run_dir'],job]).stdout);local=d/'result.zip';c.copy(shared.HOST+':'+receipt['path'],str(local))
                        if sha(local)!=receipt['sha256']:raise ValueError('transfer hash mismatch')
                        with zipfile.ZipFile(local) as z:
                            for n in z.namelist():
                                if Path(n).is_absolute() or '..' in Path(n).parts:raise ValueError('unsafe result path')
                            for n,h in json.loads(z.read('retrieval-manifest.json'))['files'].items():
                                if hashlib.sha256(z.read(n)).hexdigest()!=h:raise ValueError('result member hash mismatch')
                            z.extractall(d/'result')
                        value.update(retrieved=True,result_hashes_verified=True,run_phase=receipt['phase'])
        write(d/'status.json',value);print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    except Exception as x:
        value.update(error_type=type(x).__name__,error=str(x),automatic_retry=False);write(d/'status.json',value);print(json.dumps(value,ensure_ascii=False,indent=2),file=sys.stderr);return 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as x:print(json.dumps({'error_type':type(x).__name__,'error':str(x)},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
