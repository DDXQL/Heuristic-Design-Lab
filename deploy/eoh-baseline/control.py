#!/usr/bin/env python3
"""Mac workflow. Reuse admitted SSH/install mechanism; never runs API/solve locally."""
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
HERE=ROOT/'deploy/eoh-baseline'
spec=importlib.util.spec_from_file_location('admitted_cluster_deployment',ROOT/'deploy/cluster-mock/control.py')
shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
sys.path[:0]=[str(HERE),str(ROOT/'code'),str(ROOT)]
import eoh_gap as e
REMOTE='/public2/home/qiuqian/hdl-deploy/fjsp-eoh-J-prepared-923781f-20261113-r1'
RUN=REMOTE+'/runs/fjsp-eoh-J-baseline-20261113-r1'
BUNDLE=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-eoh-J-prepared-923781f-20261113-r1.zip')
REPORT=ROOT/'reports/fjsp-eoh-gap-prep-20261113'
EXPORT='''import hashlib,json,pathlib,sys,time,zipfile
root=pathlib.Path(sys.argv[1]);job=sys.argv[2]
if not job.isdigit():raise SystemExit('invalid job identity')
run=root/'runs/fjsp-eoh-J-baseline-20261113-r1'
if not run.is_dir():raise SystemExit('independent EoH run missing')
s=json.loads((run/'checkpoint.json').read_text())
if s['phase'] in ('running','launching') or ((run/'.execution.lock').exists() and s['phase']!='stopped'):raise SystemExit('run may still write; wait for settled end')
folder=root/'exports';folder.mkdir(exist_ok=True)
out=folder/('eoh-'+job+'-'+str(time.time_ns())+'.zip')
paths=[p for p in run.rglob('*') if p.is_file() and not p.is_symlink()]
paths += [p for p in (root/'submissions').glob('*.json') if p.is_file()]
paths += [root/'logs'/('eoh-'+job+'.out'),root/'logs'/('eoh-'+job+'.err'),root/'latest-submission.json']
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
    for n in files:z.write(root/n,n)
    z.writestr('retrieval-manifest.json',json.dumps({'job_id':job,'phase':s['phase'],'files':files},indent=2))
print(json.dumps({'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'phase':s['phase'],'job_id':job}))
'''


def query(c,d):
    record=json.loads(c.run(['cat',REMOTE+'/latest-submission.json']).stdout)
    job=record.get('job_id','')
    if record.get('state')!='submitted' or not job.isdigit():raise ValueError('missing/unknown EoH submission; no resend')
    queue=c.run(['squeue','-h','-u','qiuqian','-o','%i|%T|%C|%P'])
    account=c.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode,Elapsed,AllocCPUS,MaxRSS,NodeList'])
    (d/'squeue.txt').write_text(queue.stdout);(d/'sacct.psv').write_text(account.stdout)
    row=next((r.split('|') for r in account.stdout.splitlines() if r.split('|')[0]==job),None)
    value={'job_id':job,'active':any(r.split('|')[0]==job for r in queue.stdout.splitlines()),'Slurm_state':row[1].split()[0] if row else None,'exit_code':row[2] if row else None}
    status=c.run([shared.PY,'-s','-B',REMOTE+'/experiments/common/run_fjsp_eoh_gap.py','status','--run-dir',RUN],check=False)
    (d/'run-status.txt').write_text(status.stdout+status.stderr)
    if status.returncode==0:value['run_summary']=json.loads(status.stdout)
    else:value['run_status_error']=True
    return value


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['check-only','prepare','stage','submit','query','pause','resume','fetch'])
    ap.add_argument('--config',type=Path,default=HERE/'research.pending.json')
    ap.add_argument('--submit',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--approve-budget',type=int)
    a=ap.parse_args()
    if a.action in ('check-only','prepare'):
        value=e.check(a.config);print(json.dumps(value,ensure_ascii=False,indent=2))
        return 2 if a.action=='prepare' and value['missing_protocol_decisions'] else 0
    if a.action in ('submit','resume'):
        if not a.submit or not a.allow_api or type(a.approve_budget) is not int:raise PermissionError('manual --submit --allow-api --approve-budget ORIGINAL_CAP required')
        if a.action=='submit':
            cfg,data,refs,origin,todo=e.preflight(a.config)
            if todo:raise PermissionError('PROTOCOL_UNFROZEN: '+', '.join(todo))
            e.authorize(cfg,a.approve_budget,a.allow_api)
    elif a.submit or a.allow_api or a.approve_budget is not None:raise PermissionError('deployment/query/control/fetch must not carry API approval')
    REPORT.mkdir(parents=True,exist_ok=True);d=REPORT/(a.action+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);d.mkdir()
    value={'action':a.action,'prepared':True,'uploaded':False if a.action=='stage' else 'not_rechecked','new_EoH_compute_node_verified':False,'local_evidence':str(d),'remote_root':REMOTE,'local_API_requests':0,'local_actual_solves':0}
    try:
        with shared.Connection() as c:
            if a.action=='stage':
                expected=BUNDLE.with_suffix('.zip.sha256').read_text().split()[0]
                if hashlib.sha256(BUNDLE.read_bytes()).hexdigest()!=expected:raise ValueError('local package hash mismatch')
                # Existing environment only; do not install, repeat Mock or solve acceptance.
                inventory=c.run(['/usr/bin/python3','-s','-'],(ROOT/'deploy/cluster-mock/inspect_remote.py').read_text())
                (d/'read-only-environment.json').write_text(inventory.stdout);env=json.loads(inventory.stdout)
                if not env['environment_available'] or not env['ancestor_writable']:raise ValueError('existing environment / destination unavailable; no installation')
                incoming='/public2/home/qiuqian/hdl-deploy/eoh-incoming-20261113';c.run(['mkdir','-p',incoming]);archive=incoming+'/'+BUNDLE.name
                found=c.run(['test','-e',archive],check=False)
                if found.returncode==1:
                    c.copy(str(BUNDLE),shared.HOST+':'+archive);c.copy(str(BUNDLE.with_suffix('.zip.sha256')),shared.HOST+':'+archive+'.sha256')
                elif found.returncode or c.run(['sha256sum',archive]).stdout.split()[0]!=expected:raise ValueError('remote archive differs; preserved')
                value['uploaded']=True;shared.save(d/'status.json',value)
                installed=c.run([shared.PY,'-s','-B','-c',shared.INSTALL,archive,REMOTE,expected]);(d/'release-verification.json').write_text(installed.stdout)
                checked=c.run([shared.PY,'-s','-B',REMOTE+'/experiments/common/run_fjsp_eoh_gap.py','check-only']);(d/'check-only.json').write_text(checked.stdout)
                result=json.loads(checked.stdout)
                if result['environment_check']!='passed' or result['protocol_check']!='unfrozen_expected_rejection':raise ValueError('unexpected import/protocol outcome')
                value.update(remote_manifest_verified=True,login_import_verified=True,protocol_check=result['protocol_check'],Slurm_submitted=False)
            elif a.action=='submit':
                remote_config={**e.read(a.config),'data_manifest':REMOTE+'/preparations/eoh-gap/train21.manifest.json'}
                content=(json.dumps(remote_config,ensure_ascii=False,indent=2)+'\n').encode();digest=hashlib.sha256(content).hexdigest()
                source=d/'remote-configuration.json';source.write_bytes(content);target=REMOTE+'/approvals/'+digest+'.json'
                c.run(['mkdir','-p',REMOTE+'/approvals']);exists=c.run(['test','-e',target],check=False)
                if exists.returncode==1:c.copy(str(source),shared.HOST+':'+target)
                elif exists.returncode:raise ValueError('cannot check approved configuration path')
                if c.run(['sha256sum',target]).stdout.split()[0]!=digest:raise ValueError('uploaded configuration hash differs')
                command=[shared.PY,'-s','-B',REMOTE+'/deploy/eoh-baseline/job.py','submit','--config',target,'--submit','--allow-api','--approve-budget',str(a.approve_budget)]
                receipt=c.run(command);(d/'submit-output.json').write_text(receipt.stdout)
                value.update(manual_submission_requested=True,receipt=json.loads(receipt.stdout))
            elif a.action=='resume':
                receipt=c.run([shared.PY,'-s','-B',REMOTE+'/deploy/eoh-baseline/job.py','resume','--submit','--allow-api','--approve-budget',str(a.approve_budget)])
                (d/'resume-output.json').write_text(receipt.stdout);value.update(manual_resume_requested=True,receipt=json.loads(receipt.stdout))
            elif a.action=='pause':
                receipt=c.run([shared.PY,'-s','-B',REMOTE+'/experiments/common/run_fjsp_eoh_gap.py','pause','--run-dir',RUN]);(d/'pause.json').write_text(receipt.stdout);value.update(json.loads(receipt.stdout))
            else:
                value.update(query(c,d))
                if a.action=='fetch':
                    terminal={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}
                    if value['active'] or value['Slurm_state'] not in terminal:raise ValueError('wait for this EoH job to leave queue and reach terminal accounting')
                    receipt=json.loads(c.run([shared.PY,'-s','-B','-c',EXPORT,REMOTE,value['job_id']]).stdout)
                    local=d/'result.zip';c.copy(shared.HOST+':'+receipt['path'],str(local))
                    if hashlib.sha256(local.read_bytes()).hexdigest()!=receipt['sha256']:raise ValueError('result transfer hash mismatch')
                    with zipfile.ZipFile(local) as z:
                        for n in z.namelist():
                            if Path(n).is_absolute() or '..' in Path(n).parts:raise ValueError('unsafe result ZIP')
                        manifest=json.loads(z.read('retrieval-manifest.json'))
                        for n,h in manifest['files'].items():
                            if hashlib.sha256(z.read(n)).hexdigest()!=h:raise ValueError('result manifest mismatch: '+n)
                        z.extractall(d/'result')
                    value.update(retrieved=True,result_hashes_verified=True,result_zip_sha256=receipt['sha256'],run_phase=receipt['phase'])
                    value['new_EoH_compute_node_verified']=value.get('run_summary',{}).get('cursor',0)>0 and not value.get('run_summary',{}).get('engineering_only',True)
        shared.save(d/'status.json',value);shared.save(REPORT/('latest-'+a.action+'.json'),value);print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    except Exception as x:
        value.update(error_type=type(x).__name__,error=str(x),automatic_retry=False);shared.save(d/'status.json',value)
        print(json.dumps(value,ensure_ascii=False,indent=2),file=sys.stderr);return 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as x:print(json.dumps({'error_type':type(x).__name__,'error':str(x),'no_connection_attempted':True},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
