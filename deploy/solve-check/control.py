#!/usr/bin/env python3
"""Mac workflow for a small overlay over the already admitted remote base."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('admitted_deployment',ROOT/'deploy/cluster-mock/control.py')
shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
REMOTE='/public2/home/qiuqian/hdl-deploy/fjsp-real-solve-923781f-20261113-r1'
BASE='/public2/home/qiuqian/hdl-deploy/fjsp-noapi-923781f-20261113-r1'
BUNDLE=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-real-solve-16-923781f-20261113-r1.zip')
REPORT=ROOT/'reports/cluster-solve-check-20261113'
PY=shared.PY

EXPORT='''import hashlib,json,pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1]);job=sys.argv[2]
if not job.isdigit():raise SystemExit('invalid job')
folder=root/'exports';folder.mkdir(exist_ok=True);out=folder/('solve-'+job+'.zip')
if not out.exists():
    paths=list((root/'run').rglob('*')) if (root/'run').exists() else []
    paths += [root/'logs'/('solve-'+job+'.out'),root/'logs'/('solve-'+job+'.err'),root/'solve-submission.json']
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            if p.is_file() and not p.is_symlink():z.write(p,str(p.relative_to(root)))
print(json.dumps({'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'bytes':out.stat().st_size}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['stage','submit','query','fetch'])
    parser.add_argument('--submit',action='store_true');parser.add_argument('--approve-solves',type=int)
    parser.add_argument('--partition',default='128C_02');args=parser.parse_args()
    if args.action=='submit' and (not args.submit or args.approve_solves!=16):
        print('Submission requires --submit --approve-solves 16; no connection or solve started.');return 2
    REPORT.mkdir(parents=True,exist_ok=True)
    directory=REPORT/(args.action+'-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime())+'-'+uuid.uuid4().hex[:6]);directory.mkdir()
    status={'action':args.action,'uploaded':False if args.action=='stage' else 'previously_staged',
            'actual_solve_acceptance_verified':False,'API_requests':0,'local_evidence':str(directory)}
    try:
        with shared.Connection() as connection:
            if args.action=='stage':
                expected=BUNDLE.with_suffix('.zip.sha256').read_text().split()[0]
                if hashlib.sha256(BUNDLE.read_bytes()).hexdigest()!=expected:raise ValueError('overlay ZIP changed')
                # Verify existing base identity, then upload only the new small overlay.
                expected_base=json.loads((ROOT/'deploy/solve-check/plan.json').read_text())['base_manifest_sha256']
                if connection.run(['sha256sum',BASE+'/release.json']).stdout.split()[0]!=expected_base:raise ValueError('admitted remote base changed; no redeployment attempted')
                incoming='/public2/home/qiuqian/hdl-deploy/solve-incoming-20261113';connection.run(['mkdir','-p',incoming])
                archive=incoming+'/'+BUNDLE.name
                old=connection.run(['test','-e',archive],check=False)
                if old.returncode==1:
                    connection.copy(str(BUNDLE),shared.HOST+':'+archive)
                    connection.copy(str(BUNDLE.with_suffix('.zip.sha256')),shared.HOST+':'+archive+'.sha256')
                elif old.returncode or connection.run(['sha256sum',archive]).stdout.split()[0]!=expected:
                    raise ValueError('existing remote overlay is unknown/different; preserved')
                status['uploaded']=True;shared.save(directory/'status.json',status)
                installed=connection.run([PY,'-s','-B','-c',shared.INSTALL,archive,REMOTE,expected])
                (directory/'overlay-verification.json').write_text(installed.stdout)
                checked=connection.run([PY,'-s','-B',REMOTE+'/deploy/solve-check/accept.py','check'])
                (directory/'check-only.json').write_text(checked.stdout)
                status.update(overlay_verified=True,base_reused=True,check_only_passed=True,actual_solves=0,submitted=False)
            elif args.action=='submit':
                value=connection.run([PY,'-s','-B',REMOTE+'/deploy/solve-check/job.py','--partition',args.partition,'--submit','--approve-solves','16'])
                (directory/'submit-output.txt').write_text(value.stdout)
                status.update(manual_submission_requested=True,max_physical_solves=16)
            else:
                claim=json.loads(connection.run(['cat',REMOTE+'/solve-submission.json']).stdout)
                job=claim.get('job_id','')
                if claim.get('state')!='submitted' or not job.isdigit():raise ValueError('unknown submission; no resend')
                queue=connection.run(['squeue','-h','-u','qiuqian','-o','%i|%T|%C|%P'])
                account=connection.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode,Elapsed,AllocCPUS,MaxRSS,NodeList'])
                (directory/'squeue.txt').write_text(queue.stdout);(directory/'sacct.psv').write_text(account.stdout)
                row=next((v.split('|') for v in account.stdout.splitlines() if v.split('|')[0]==job),None)
                active=any(v.split('|')[0]==job for v in queue.stdout.splitlines())
                status.update(job_id=job,active=active,Slurm_state=row[1].split()[0] if row else None,exit_code=row[2] if row else None)
                if args.action=='fetch':
                    terminal={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}
                    if active or status['Slurm_state'] not in terminal:raise ValueError('job active or terminal accounting missing')
                    exported=json.loads(connection.run([PY,'-s','-B','-c',EXPORT,REMOTE,job]).stdout)
                    local=directory/'result.zip';connection.copy(shared.HOST+':'+exported['path'],str(local))
                    if hashlib.sha256(local.read_bytes()).hexdigest()!=exported['sha256']:raise ValueError('result ZIP transfer hash mismatch')
                    with zipfile.ZipFile(local) as z:
                        for name in z.namelist():
                            p=Path(name)
                            if p.is_absolute() or '..' in p.parts:raise ValueError('unsafe result ZIP path')
                        z.extractall(directory/'result')
                    result=directory/'result/run';manifest=result/'results-manifest.json'
                    if manifest.exists():
                        for name,value in json.loads(manifest.read_text())['files'].items():
                            p=(result/name).resolve()
                            if not p.is_relative_to(result.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=value:
                                raise ValueError('result manifest mismatch: '+name)
                        status['result_hashes_verified']=True
                    accepted=result/'acceptance.json'
                    if accepted.exists():
                        a=json.loads(accepted.read_text())
                        status['actual_solve_acceptance_verified']=(status['Slurm_state']=='COMPLETED' and status['exit_code']=='0:0'
                            and a['job_id']==job and a['passed'] and a['kind']=='REAL_EVALUATOR_ENGINEERING_ACCEPTANCE'
                            and a['physical_solves']['confirmed_completed']==16 and a['reserved_solves']==16
                            and a['API']['model_requests']==0 and not a['API']['real_client_modules_loaded'])
                    status.update(retrieved=True,result_zip_sha256=exported['sha256'])
        shared.save(directory/'status.json',status);shared.save(REPORT/('latest-'+args.action+'.json'),status)
        print(json.dumps(status,ensure_ascii=False,indent=2))
        return 2 if args.action=='fetch' and not status['actual_solve_acceptance_verified'] else 0
    except Exception as error:
        status.update(error_type=type(error).__name__,error=str(error))
        shared.save(directory/'status.json',status);shared.save(REPORT/('latest-'+args.action+'.json'),status)
        print(json.dumps(status,ensure_ascii=False,indent=2),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
