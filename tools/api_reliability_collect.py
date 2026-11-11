"""One SSH session for Slurm/state/log collection; no API/client imports.

Kept outside the frozen runtime manifest: this never changes that release or budget.
Passwords are handled by SSH on the user's terminal, never read by this program.
Default is read-only. --disable-requeue explicitly disables node-failure requeue
on the identity-checked existing job; it never submits, cancels or requeues a job.
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import datetime,getpass,hashlib,json,os,re,socket,subprocess,sys
from pathlib import Path
job=sys.argv[1]
assert job.isdecimal()
resources='--resources' in sys.argv[2:]
disable_requeue='--disable-requeue' in sys.argv[2:]
base=Path('/public2/home/qiuqian/hdl-deploy/api-common-v5-20261111')
home=Path.home()
def scrub(s):return re.sub(r'(?i)(bearer\s+\S+|sk-[A-Za-z0-9_-]+)','[REDACTED]',s)
def query(args):
 try:
  p=subprocess.run(args,capture_output=True,text=True,timeout=25)
  stdout=scrub(p.stdout);stderr=scrub(p.stderr)
  return {'command':args,'returncode':p.returncode,'stdout':stdout[-20000:],'stderr':stderr[-2000:],
          'stdout_truncated':len(stdout)>20000,'stderr_truncated':len(stderr)>2000}
 except Exception as e:return {'command':args,'error_type':type(e).__name__}
def terminal_accounting(result):
 if result.get('returncode')!=0 or result.get('stdout_truncated'):return None
 states='COMPLETED|FAILED|CANCELLED|TIMEOUT|NODE_FAIL|OUT_OF_MEMORY|BOOT_FAIL|PREEMPTED|DEADLINE|REVOKED'
 for line in result.get('stdout','').splitlines():
  if not line.split() or line.split()[0]!=job:continue
  match=re.search(r'\s('+states+r')\+?\s+(\d+:\d+)(?:\s|$)',line)
  if match:return {'state':match[1],'exit_code':match[2]}
 return None
def snapshot(path,kind='json'):
 try:return snapshot_file(path,kind)
 except OSError as error:return {'path':str(path),'read_error_type':type(error).__name__}
def snapshot_file(path,kind='json'):
 info={'path':str(path),'exists':path.exists()}
 if not info['exists']:return info
 resolved=path.resolve()
 if not (resolved.is_relative_to(home.resolve()) or resolved.is_relative_to(base.resolve())):
  return {**info,'skipped':'outside personal/release directory'}
 if path.is_symlink():return {**info,'skipped':'symlink preserved, not read'}
 if not path.is_file():return {**info,'skipped':'not a regular file'}
 stat=path.stat();info.update(bytes=stat.st_size,mtime=stat.st_mtime)
 if kind=='json':
  if stat.st_size>1048576:return {**info,'skipped':'over 1MiB collection bound'}
  raw=path.read_bytes();info['sha256']=hashlib.sha256(raw).hexdigest()
  try:info['value']=json.loads(scrub(raw.decode('utf-8')))
  except (ValueError,UnicodeError):info['invalid_json']=True
 else:
  with path.open('rb') as f:f.seek(max(0,stat.st_size-16000));raw=f.read(16000)
  info.update(tail=scrub(raw.decode('utf-8',errors='replace')),tail_bytes=len(raw))
 return info
out={'at_utc8':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
     'job_id':job,'model_requests_added':0,'solves_added':0,'submissions_added':0,
     'identity':{'user':getpass.getuser(),'hostname':socket.gethostname(),'home':str(home)},
     'queue':query(['squeue','-j',job,'-h','-o','%i %j %T %R']),
     'accounting':query(['sacct','-j',job,'--format=JobID,JobName%24,State,ExitCode,Elapsed,NodeList']),
     'job_details':query(['scontrol','show','job',job]),'states':[],'logs':[]}
if resources:
 match=re.search(r'\bPartition=([A-Za-z0-9_.+,-]+)',out['job_details'].get('stdout',''))
 partition=match[1] if match else '128C_02'
 out['resources']={
  'partition_query_target':partition,
  'partition_source':'job_details' if match else 'frozen_submission_hint; current job partition unknown',
  'partitions':query(['sinfo','-a','-h','-o','%P %a %l %D %t %C']),
  'partition_policy':query(['scontrol','show','partition']),
  'partition_queue':query(['squeue','-p',partition,'-h','-o','%T %C %D %r']),
  'associations':query(['sacctmgr','-P','show','assoc','where','user=qiuqian']),
  'qos':query(['sacctmgr','-P','show','qos','where','name=normal']),
  'reservations':query(['scontrol','show','reservation'])}
paths=[home/'hdl-api-validation/mac-cluster-api-v5-20261111/cluster',
 Path('/public2/home/qiuqian/hdl-api-validation/mac-cluster-api-v5-20261111/cluster')]
for state in dict.fromkeys(paths):
 row={'path':str(state),'exists':state.exists(),'owner_lock_exists':(state/'owner.lock').exists(),'files':[]}
 # Explicit allowlist; never walk HOME or open any credential/config file.
 names=['claim.json','ledger.json','export.json','Stop_request.json',
        'reservations/01.json','reservations/02.json','responses/01.json','responses/02.json']
 row['files']=[snapshot(state/name) for name in names]
 out['states'].append(row)
logpaths=[base/'logs'/('api-v5-'+job+'.out'),base/'logs'/('api-v5-'+job+'.err')]
for key in ['StdOut','StdErr']:
 m=re.search(r'\b'+key+r'=(\S+)',out['job_details'].get('stdout',''))
 if m:
  path=Path(m[1])
  if job in path.name and path.suffix in ('.out','.err'):logpaths.append(path)
out['logs']=[snapshot(path,'log') for path in dict.fromkeys(logpaths)]
out['release_plan']=snapshot(base/'deploy/api-common/plan.json')
if disable_requeue:
 before=query(['scontrol','show','job',job]);out['job_details_before_update']=before
 details=before.get('stdout','')
 fields=dict(re.findall(r'\b(UserId|Command|JobState|Requeue)=([^\s]+)',details))
 owner=re.fullmatch(r'qiuqian\((\d+)\)',fields.get('UserId',''))
 valid=(before.get('returncode')==0 and owner and int(owner[1])==os.getuid()
        and fields.get('Command')==str(base/'deploy/api-common/cluster.sbatch')
        and out['release_plan'].get('sha256')=='f75598d47fec350444f7caafdab34327f92011a8702eb94615b04ba32b0d828b')
 terminal=terminal_accounting(out['accounting'])
 if before.get('returncode')!=0 and terminal:
  out['requeue_policy_update']={'status':'terminal_no_update','job_state':terminal['state'],
      'accounting_exit_code':terminal['exit_code'],'source':'sacct exact parent job',
      'reason':'job left active controller; no policy update needed; Requeue=0 not claimed'}
 elif not valid:out['requeue_policy_update']={'status':'blocked','reason':'job owner/command/frozen plan identity not verified; no update'}
 elif fields.get('JobState') not in ('PENDING','RUNNING','CONFIGURING','SUSPENDED'):
  out['requeue_policy_update']={'status':'terminal_no_update','job_state':fields.get('JobState')}
 elif fields.get('Requeue')=='0':out['requeue_policy_update']={'status':'verified','already_disabled':True}
 else:
  result=query(['scontrol','update','JobId='+job,'Requeue=0'])
  after=query(['scontrol','show','job',job]);out['job_details_after_update']=after
  verified=(result.get('returncode')==0 and after.get('returncode')==0 and re.search(r'\bRequeue=0\b',after.get('stdout','')) is not None)
  out['requeue_policy_update']={'status':'verified' if verified else 'not_verified','result':result,
      'action':'disable node-failure requeue only; no cancel, submission, release or replay'}
out['finished_at_utc8']=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
print(json.dumps(out,ensure_ascii=False,indent=2))
'''


def summary(value):
    states = []
    for entry in value.get('states', []):
        ledger = next((f.get('value') for f in entry['files']
                       if f['path'].endswith('/ledger.json') and 'value' in f), None)
        states.append({'path': entry['path'], 'exists': entry['exists'],
                       'phase': ledger.get('status') if ledger else None,
                       'totals': ledger.get('totals') if ledger else None})
    fields = dict(re.findall(r'\b(JobState|Reason|Partition|Account|QOS|Requeue|Restarts|RunTime|TimeLimit|SubmitTime|EligibleTime|StartTime|NumNodes|NumCPUs)=([^\s]+)',
                             value.get('job_details_after_update', value.get('job_details_before_update', value.get('job_details', {}))).get('stdout', '')))
    resource_checks = {k: {name: v.get(name) for name in ('returncode', 'error_type', 'stdout_truncated') if name in v}
                       for k, v in value.get('resources', {}).items() if isinstance(v, dict)}
    return {'job_id': value['job_id'], 'queue': value.get('queue'), 'job_fields': fields,
            'accounting': value.get('accounting'), 'states': states,
            'resource_checks': resource_checks,
            'requeue_policy_update': value.get('requeue_policy_update'),
            'logs_found': [f['path'] for f in value.get('logs', []) if f.get('exists')],
            'requests_added': 0, 'solves_added': 0, 'submissions_added': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', default='609676')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--resources', action='store_true', help='also read partition, association, QoS and reservation state; never modify jobs')
    parser.add_argument('--disable-requeue', action='store_true', help='explicitly disable node-failure requeue on this identity-checked existing job; no submit/cancel/requeue')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9]+', args.job_id):
        parser.error('job-id must contain digits only')
    if args.check_only:
        compile(REMOTE, '<read-only-remote-collector>', 'exec')
        print(json.dumps({'offline': True, 'requests_added': 0, 'solves_added': 0,
                          'submissions_added': 0, 'job_id': args.job_id,
                          'resource_queries': 6 if args.resources else 0,
                          'would_disable_requeue': args.disable_requeue}))
        return 0
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
    directory = ROOT/'reports/api-common-20261111'/f'collected-{stamp}-{uuid.uuid4().hex[:8]}'
    directory.mkdir()
    command = ['ssh', '-o', 'NumberOfPasswordPrompts=1', '-o', 'ConnectTimeout=8',
               '-o', 'ProxyCommand=ssh -o NumberOfPasswordPrompts=1 -o ConnectTimeout=8 -W %h:%p custom@222.201.144.188',
               'qiuqian@110.1.2.1',
               '/public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B - '+args.job_id+(' --resources' if args.resources else '')+(' --disable-requeue' if args.disable_requeue else '')]
    # SSH opens /dev/tty itself for authentication; no key reads or password capture.
    result = subprocess.run(command, input=REMOTE, text=True, stdout=subprocess.PIPE)
    status = {'ssh_exit_code': result.returncode, 'job_id': args.job_id,
              'stdout_bytes': len(result.stdout.encode()),
              'stdout_sha256': hashlib.sha256(result.stdout.encode()).hexdigest(),
              'requests_added': 0, 'solves_added': 0, 'submissions_added': 0}
    try:
        value = json.loads(result.stdout)
        if result.returncode or value.get('job_id') != args.job_id:
            raise ValueError('SSH or job identity differs')
    except ValueError:
        (directory/'collection-status.json').write_text(json.dumps(status, indent=2)+'\n')
        print('只读取证未完成；未调用模型或提交作业。记录：'+str(directory), file=sys.stderr)
        return 2
    with (directory/'remote.json').open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n')
    status.update(result=summary(value), output=str(directory/'remote.json'))
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 2 if value.get('requeue_policy_update', {}).get('status') in ('blocked','not_verified') else 0


if __name__ == '__main__':
    raise SystemExit(main())
