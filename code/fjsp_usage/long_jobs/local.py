"""Small macOS launchd one-shot supervisor and candidate-boundary loop.

Current executable adapter is SYNTHETIC ONLY. A real evaluator must be integrated
and frozen in a future authorized protocol; this module cannot resume old A4.
No provider or FJSP evaluation imports. No automatic restart or stale-lock removal.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

from fjsp_usage.a4_static.engine import Campaign,read,write,sha,sample_indices

ROOT=Path(__file__).resolve().parents[3]

def clock():
    return {'utc':datetime.now(timezone.utc).isoformat(),'wall':time.time(),
            'monotonic':time.monotonic(),'CPU':time.process_time()}

def event(directory,kind,**values):
    with (directory/'Events.jsonl').open('a') as f:
        f.write(json.dumps({'event':kind,**clock(),**values})+'\n');f.flush();os.fsync(f.fileno())

def sources():
    from fjsp_usage.a4_static import engine
    return {str(path):sha(path) for path in (Path(__file__).resolve(),Path(engine.__file__).resolve(),ROOT/'tools/local_long_job.py')}

def create_toy(directory,delay=.4,crash=False):
    directory=Path(directory).resolve()
    if not 0<=delay<=2:raise ValueError('bounded engineering delay only')
    p={'mode':'synthetic-engineering-only','space_size':7,'queries_per_repeat':3,'search_seeds':[17],
       'instances':[{'file':'SYNTHETIC-A','LB':2.},{'file':'SYNTHETIC-B','LB':3.}],
       'new_evaluation_cap':6,'new_solve_pass_cap':12}
    Campaign.create(directory,p,[sample_indices(7,3,17)])
    job={'mode':'synthetic-engineering-only','job_token':uuid.uuid4().hex,'delay':delay,'crash':crash,
         'source_files':sources(),'protocol_sha256':sha(directory/'Protocol.json'),
         'plan_sha256':sha(directory/'Plans.json'),'python':sys.executable,
         'formal_FJSP_cap':0,'API_cap':0}
    write(directory/'Job.json',job)
    return directory

def check(directory,validate_journal=True):
    directory=Path(directory).resolve();j=read(directory/'Job.json')
    if j['mode']!='synthetic-engineering-only' or j['formal_FJSP_cap']!=0 or j['API_cap']!=0:
        raise PermissionError('Only synthetic adapter is authorized/implemented')
    if sha(directory/'Protocol.json')!=j['protocol_sha256'] or sha(directory/'Plans.json')!=j['plan_sha256']:
        raise ValueError('immutable job protocol/plan changed')
    for n,h in j['source_files'].items():
        if sha(n)!=h:raise ValueError('job source changed')
    if (directory/'Stop.json').exists():raise ValueError('persistent Stop; never clear automatically')
    if validate_journal:Campaign(directory).validate()  # reserved/orphan results are not resumable
    return j

def run_boundaries(campaign,evaluate,deadline,check_identity,clock_fn=clock,gap_limit=2.):
    """Future adapter hook: single query at a time; pause only after durable commit.

    Completed quality is retained on a clock gap; further launches stop for review.
    It never overrides the campaign's own source/budget/Stop/unknown protection.
    """
    d=campaign.directory
    while True:
        check_identity();p,plans,state,flat=campaign.validate()
        if state['phase'] in ('completed','wall_budget_stopped'):return state['phase']
        if (d/'Pause_request.json').exists():return 'paused_at_candidate_boundary'
        before=clock_fn()
        if before['wall']+650>deadline:return 'launch_deadline_stopped'
        campaign.execute(evaluate,limit=1,clock=lambda:clock_fn()['wall'],wall_deadline=deadline)
        check_identity();campaign.validate()
        after=clock_fn();gap=(after['wall']-before['wall'])-(after['monotonic']-before['monotonic'])
        if abs(gap)>gap_limit:
            write(d/'Clock_gap.json',{'before':before,'after':after,'wall_minus_monotonic_seconds':gap,
                  'action':'completed result retained; no further launch; manual review','result_reclassified':False})
            return 'clock_gap_paused_at_boundary'

def work(directory):
    directory=Path(directory).resolve()
    def guard(name,args):
        if name in ('socket.connect','socket.getaddrinfo'):
            raise PermissionError('network forbidden in synthetic long-job validation')
        if name=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)) and str(args[0]).endswith('.fjsp'):
            raise PermissionError('formal instance access forbidden')
    sys.addaudithook(guard)
    j=check(directory)
    if any((directory/n).exists() for n in ('Run_identity.json','Run_clock.json','End_summary.json')):
        raise ValueError('one-shot job already started or unknown clock; no implicit resume/retry')
    fd=os.open(directory/'.job.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    identity={'pid':os.getpid(),'ppid':os.getppid(),'token':j['job_token'],'source_files':j['source_files'],
              'process_start':subprocess.check_output(['/bin/ps','-p',str(os.getpid()),'-o','lstart='],text=True).strip(),**clock()}
    with os.fdopen(fd,'w') as f:json.dump(identity,f)
    write(directory/'Lock_receipt.json',identity);write(directory/'Run_identity.json',identity)
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    begun=clock();state=None
    try:
        event(directory,'job_started',pid=os.getpid(),ppid=os.getppid())
        # Persistent launch allowance; creation is once only, never reset on restart.
        write(directory/'Run_clock.json',{'start_utc_epoch':begun['wall'],'deadline_utc_epoch':begun['wall']+7200})
        state=read(directory/'checkpoint.json');state['run_clock_sha256']=sha(directory/'Run_clock.json');write(directory/'checkpoint.json',state)
        def evaluate(index,folder,reserve):
            reserve();event(directory,'synthetic_candidate_started',index=index)
            write(directory/'Active_candidate.json',{'index':index,'folder':str(folder),'status':'in_flight'})
            if j['crash']:os._exit(13)  # intentional synthetic crash; reservation/lock retained
            time.sleep(j['delay'])
            rows=[{'file':'SYNTHETIC-A','lower_bound':2.,'makespan':4+index,'score':-(4+index)/2.,'feasible':True},
                  {'file':'SYNTHETIC-B','lower_bound':3.,'makespan':6+index,'score':-(6+index)/3.,'feasible':True}]
            value={'valid':True,'fitness':sum(x['score'] for x in rows)/2,'total_instances':2,'instances':rows}
            event(directory,'synthetic_candidate_returned',index=index)
            return value,'new',{'synthetic':True,'pid':os.getpid(),'source_files':j['source_files']}
        phase=run_boundaries(Campaign(directory),evaluate,begun['wall']+7200,lambda:check(directory))
        state=Campaign(directory).validate()[2]
        write(directory/'End_summary.json',{'phase':phase,'completed_queries':len(state['queries']),
            'pid':os.getpid(),'self_completion_record':clock(),'started':begun,
            'formal_FJSP_solves':0,'API':0,'exit_intended':0,
            'note':'self completion is recorded before OS exit; launchd exit status is a later observation'})
        event(directory,'job_summary_written',phase=phase)
    except BaseException as e:
        if not (directory/'Stop.json').exists():write(directory/'Stop.json',{'type':type(e).__name__,'error':str(e),'automatic_retry':False})
        write(directory/'End_summary.json',{'phase':'stopped_on_error','error':str(e),'self_completion_record':clock(),'formal_FJSP_solves':0,'API':0,'automatic_retry':False})
        raise
    finally:
        # Release only our matching lock; stale/unknown ownership is never removed.
        if read(directory/'.job.lock').get('token')==j['job_token']:(directory/'.job.lock').unlink()

def launch(directory):
    directory=Path(directory).resolve();check(directory)
    if (directory/'Launch_receipt.json').exists():raise ValueError('already submitted; never auto resubmit')
    if (directory/'.job.lock').exists():raise ValueError('existing job lock; no automatic stale-lock removal')
    j=read(directory/'Job.json');label='org.fjsp.research.toy.'+j['job_token'];domain=f'gui/{os.getuid()}'
    args=[str(ROOT/'.venv/bin/python'),'-B',str(ROOT/'tools/local_long_job.py'),'work','--job-dir',str(directory)]
    plist={'Label':label,'ProgramArguments':args,'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':False,
           'StandardOutPath':str(directory/'Stdout.log'),'StandardErrorPath':str(directory/'Stderr.log'),
           'EnvironmentVariables':{'PYTHONPATH':str(ROOT/'code')+':'+str(ROOT)}}
    path=directory/'Launch.plist';path.write_bytes(plistlib.dumps(plist))
    # Persist reservation BEFORE bootstrap; an ambiguous bootstrap is never retried.
    write(directory/'Launch_receipt.json',{'label':label,'domain':domain,'controller_pid':os.getpid(),
        'status':'submission_reserved','argv':args,'plist_sha256':sha(path),**clock()})
    result=subprocess.run(['/bin/launchctl','bootstrap',domain,str(path)],capture_output=True,text=True)
    write(directory/'Submission_result.json',{'returncode':result.returncode,'stderr':result.stderr,**clock()})
    if result.returncode:raise RuntimeError('launchd bootstrap failed; inspect evidence, do not auto retry: '+result.stderr)
    return label

def observe(directory):
    directory=Path(directory).resolve();j=read(directory/'Launch_receipt.json')
    r=subprocess.run(['/bin/launchctl','print',j['domain']+'/'+j['label']],capture_output=True,text=True)
    keep=[line.strip() for line in r.stdout.splitlines() if any(key in line for key in ('state =','pid =','last exit code =','runs ='))]
    return {'launchctl_returncode':r.returncode,'fields':keep,'observed_at':clock(),
        'summary':read(directory/'End_summary.json') if (directory/'End_summary.json').exists() else None,
        'lock_present':(directory/'.job.lock').exists(),'Stop_present':(directory/'Stop.json').exists()}

def request_pause(directory,reason):
    directory=Path(directory).resolve();check(directory,validate_journal=False)
    write(directory/'Pause_request.json',{'reason':reason,'policy':'finish current query and durable commit, then pause',**clock()})
