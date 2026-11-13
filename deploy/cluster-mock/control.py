#!/usr/bin/env python3
"""Mac terminal workflow: stage, explicit manual submit, query, or retrieve."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid
for _name in list(os.environ):
    if any(token in _name.upper() for token in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN','SECRET')):
        os.environ.pop(_name,None)

ROOT=Path(__file__).resolve().parents[2]
BUNDLE=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-cluster-noapi-923781f-20261113-r1.zip')
REMOTE='/public2/home/qiuqian/hdl-deploy/fjsp-noapi-923781f-20261113-r1'
PY='/public2/home/qiuqian/hdl-envs/portable-v2/bin/python'
HOST='qiuqian@110.1.2.1'
JUMP='custom@222.201.144.188'
REPORT=ROOT/'reports/cluster-noapi-20261113'


def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


class Connection:
    def __enter__(self):
        self.directory=Path('/tmp')/('hdl-noapi-'+str(os.getuid())+'-'+uuid.uuid4().hex[:8])
        self.directory.mkdir(mode=0o700);self.socket=str(self.directory/'s')
        # This is the sole interactive authentication step per invocation.
        subprocess.run(['ssh','-M','-N','-f','-S',self.socket,'-o','ControlPersist=600',
                        '-o','ConnectTimeout=15','-o','NumberOfPasswordPrompts=1','-J',JUMP,HOST],check=True)
        return self
    def run(self,args,source=None,check=True):
        result=subprocess.run(['ssh','-S',self.socket,'-o','BatchMode=yes','-o','ConnectTimeout=10',HOST,
                               shlex.join(args)],input=source,text=True,capture_output=True)
        if check and result.returncode:raise RuntimeError('remote command failed: '+result.stderr[-3000:])
        return result
    def copy(self,source,destination,recursive=False):
        cmd=['scp','-o','ControlPath='+self.socket,'-o','BatchMode=yes']
        if recursive:cmd.append('-r')
        subprocess.run(cmd+[source,destination],check=True)
    def __exit__(self,*args):
        subprocess.run(['ssh','-S',self.socket,'-O','exit',HOST],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


INSTALL='''import hashlib,json,pathlib,sys,zipfile
archive=pathlib.Path(sys.argv[1]);root=pathlib.Path(sys.argv[2]);expected=sys.argv[3]
if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise SystemExit('uploaded ZIP SHA mismatch')
with zipfile.ZipFile(archive) as z:
    for n in z.namelist():
        p=pathlib.PurePosixPath(n)
        if p.is_absolute() or '..' in p.parts:raise SystemExit('unsafe ZIP path')
    release=json.loads(z.read('release.json'))
    if root.exists():
        if not (root/'release.json').exists() or (root/'release.json').read_bytes()!=z.read('release.json'):
            raise SystemExit('remote release already exists with different identity; preserve it')
    else:
        root.mkdir();z.extractall(root)
for n,h in release['files'].items():
    p=(root/n).resolve()
    if not p.is_relative_to(root.resolve()) or (root/n).is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:
        raise SystemExit('remote release file mismatch: '+n)
print(json.dumps({'uploaded':True,'manifest_verified':True,'remote_root':str(root),'files':len(release['files'])}))
'''


def stage(connection,directory,progress):
    expected=BUNDLE.with_suffix('.zip.sha256').read_text().split()[0]
    if hashlib.sha256(BUNDLE.read_bytes()).hexdigest()!=expected:raise ValueError('local package hash mismatch')
    result=connection.run(['/usr/bin/python3','-s','-'],(ROOT/'deploy/cluster-mock/inspect_remote.py').read_text())
    (directory/'preflight.json').write_text(result.stdout)
    preflight=json.loads(result.stdout)
    progress['read_only_inventory_returned']=True
    if not preflight['environment_available'] or not preflight['ancestor_writable']:
        raise ValueError('existing environment or destination permission unavailable; no installation attempted')
    incoming='/public2/home/qiuqian/hdl-deploy/noapi-incoming-20261113'
    connection.run(['mkdir','-p',incoming])
    remote_archive=incoming+'/'+BUNDLE.name
    existing=connection.run(['test','-e',remote_archive],check=False)
    if existing.returncode==0:
        old=connection.run(['sha256sum',remote_archive]).stdout.split()[0]
        if old!=expected:raise ValueError('different remote archive exists; preserve it')
    elif existing.returncode==1:
        connection.copy(str(BUNDLE),HOST+':'+remote_archive)
        connection.copy(str(BUNDLE.with_suffix('.zip.sha256')),HOST+':'+remote_archive+'.sha256')
    else:raise ValueError('cannot determine remote archive existence')
    progress['uploaded']=True;save(directory/'status.json',progress)
    installed=connection.run([PY,'-s','-B','-c',INSTALL,remote_archive,REMOTE,expected])
    (directory/'upload-verification.json').write_text(installed.stdout)
    progress['remote_manifest_verified']=True;save(directory/'status.json',progress)
    checked=connection.run([PY,'-s','-B',REMOTE+'/deploy/cluster-mock/accept.py','check'])
    (directory/'login-import-check.json').write_text(checked.stdout)
    return {**progress,'prepared':True,'uploaded':True,'remote_manifest_verified':True,'login_import_verified':True,
            'compute_node_verified':False,'remote_root':REMOTE,'local_evidence':str(directory),
            'protocol_check':'unfrozen_expected_rejection','Slurm_submitted':False}


def job_id(connection):
    record=json.loads(connection.run(['cat',REMOTE+'/mock-submission.json']).stdout)
    value=record.get('job_id','')
    if record.get('state')!='submitted' or not value.isdigit():raise ValueError('job ID missing/unknown; do not resubmit')
    return value


def query(connection,directory):
    job=job_id(connection)
    queue=connection.run(['squeue','-h','-u','qiuqian','-o','%i|%T|%C|%P'],check=False)
    account=connection.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode,Elapsed,AllocCPUS,MaxRSS,NodeList'],check=False)
    (directory/'squeue.txt').write_text(queue.stdout+queue.stderr)
    (directory/'sacct.psv').write_text(account.stdout+account.stderr)
    if queue.returncode or account.returncode:raise ValueError('Slurm metadata query failed; state remains unknown')
    row=next((line.split('|') for line in account.stdout.splitlines() if line.split('|')[0]==job),None)
    state=row[1].split()[0] if row else None
    active=any(row.split('|')[0]==job for row in queue.stdout.splitlines())
    return {'job_id':job,'active':active,'accounting_state':state,'exit_code':row[2] if row else None,
            'remote_root':REMOTE,'local_evidence':str(directory)}


def fetch(connection,directory):
    result=query(connection,directory);job=result['job_id']
    terminal={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}
    if result['active'] or result['accounting_state'] not in terminal:raise ValueError('job active or terminal accounting missing; do not claim a finished copy')
    connection.copy(HOST+':'+REMOTE+'/acceptance/job-'+job,str(directory/'result'),recursive=True)
    for suffix in ('out','err'):
        connection.copy(HOST+':'+REMOTE+'/logs/mock-'+job+'.'+suffix,str(directory/('mock-'+job+'.'+suffix)))
    root=directory/'result';manifest=json.loads((root/'results-manifest.json').read_text())
    for name,value in manifest['files'].items():
        p=(root/name).resolve()
        if not p.is_relative_to(root.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=value:
            raise ValueError('retrieved result hash/path mismatch: '+name)
    acceptance=json.loads((root/'acceptance.json').read_text())
    isolation=acceptance['isolation']
    verified=(result['accounting_state']=='COMPLETED' and result['exit_code']=='0:0'
              and acceptance['job_id']==job and acceptance['engine_commit']=='923781f05686f1899c24fd7899fb3bc6b1df1562'
              and acceptance['passed'] and acceptance['serial_parallel_resume_equal']
              and isolation['model_requests']==0 and isolation['formal_solves']==0 and not isolation['real_client_modules_loaded'])
    return {**result,'retrieved':True,'result_hashes_verified':True,'compute_node_verified':verified,
            'model_requests':0,'formal_solves':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['stage','submit','query','fetch'])
    parser.add_argument('--partition',default='128C_02');parser.add_argument('--submit',action='store_true')
    args=parser.parse_args()
    if args.action=='submit' and not args.submit:
        print(shlex.join([PY,'-s','-B',REMOTE+'/deploy/cluster-mock/job.py','--partition',args.partition,'--submit']))
        return 0
    REPORT.mkdir(parents=True,exist_ok=True)
    directory=REPORT/(args.action+'-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime())+'-'+uuid.uuid4().hex[:6])
    directory.mkdir()
    result={'action':args.action,'prepared':True,'uploaded':False if args.action=='stage' else 'unknown',
            'compute_node_verified':False,'local_evidence':str(directory)}
    try:
        with Connection() as connection:
            if args.action=='stage':result=stage(connection,directory,result)
            elif args.action=='submit':
                submitted=connection.run([PY,'-s','-B',REMOTE+'/deploy/cluster-mock/job.py','--partition',args.partition,'--submit'])
                (directory/'submit-output.txt').write_text(submitted.stdout)
                result={'manual_submit_requested':True,'compute_node_verified':False,'local_evidence':str(directory)}
            elif args.action=='query':result=query(connection,directory)
            else:result=fetch(connection,directory)
        save(directory/'status.json',result);save(REPORT/('latest-'+args.action+'.json'),result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if args.action=='fetch' and not result.get('compute_node_verified') else 0
    except Exception as error:
        result.update(error_type=type(error).__name__,error=str(error))
        save(directory/'status.json',result);save(REPORT/('latest-'+args.action+'.json'),result)
        print(json.dumps(result,ensure_ascii=False,indent=2),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
