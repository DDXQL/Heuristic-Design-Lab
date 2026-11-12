"""Opt-in engineering contract for the existing parent-coverage coordinator.

No state definitions, search operators, provider implementation or automatic
retries live here. A real run additionally needs an external frozen protocol.
"""
import json
import math
import os
from pathlib import Path
import socket
import time

from .storage import digest, read, sha, write

VERSION = 'frozen-execution-v1'
THREAD_ENV = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
              'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')
FIELDS = {'version', 'run_id', 'group', 'allocated_cpus', 'window_seconds',
          'segment_seconds', 'drain_seconds', 'milestone_attempts',
          'initialization_policy', 'state_binding', 'client_binding',
          'account_exclusion', 'account_gate', 'min_request_interval_seconds',
          'source_cost'}


def validate_contract(c):
    x = c['execution_contract']
    if not isinstance(x, dict) or set(x) != FIELDS or x['version'] != VERSION:
        raise ValueError('explicit frozen execution contract required')
    for key in ('run_id', 'group'):
        if not isinstance(x[key], str) or not x[key] or any(v not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for v in x[key]):
            raise ValueError('safe explicit identity required: ' + key)
    for key in ('allocated_cpus', 'window_seconds', 'segment_seconds', 'drain_seconds'):
        if type(x[key]) is not int or x[key] <= 0:
            raise ValueError('positive explicit resource/time required: ' + key)
    if x['initialization_policy'] != 'fixed_population_slots_no_refill':
        raise ValueError('only a fixed N-slot initialization plan is implemented; no success refill')
    if c['initialization'] != 'llm' or c['population_size'] > c['initialization_request_cap']:
        raise ValueError('explicit independent N-slot initialization budget required')
    if c['problem'] != 'fjsp':
        raise ValueError('TSP must supply its frozen reference adapter before enabling this profile')
    n = c['generation_request_cap']
    if type(n) is not int or n <= 0 or c['generations'] != math.ceil(n/(2*c['population_size'])):
        raise ValueError('generations must cover exactly the declared attempt prefix of the 2N plan')
    if x['allocated_cpus'] < 1 + max(c['api_concurrency'], c['evaluation_concurrency']):
        raise ValueError('CPU allocation must include controller plus the larger bounded worker wave')
    # API and evaluation waves run in stages, not simultaneously.
    bound = drain_bound(c, 1)
    if x['drain_seconds'] < bound or x['segment_seconds'] <= x['drain_seconds']:
        raise ValueError('segment/drain cannot cover one sequential API/evaluation wave')
    m = x['milestone_attempts']
    if not isinstance(m, list) or m != sorted(set(m)) or any(type(v) is not int or not 1 <= v <= n for v in m):
        raise ValueError('milestones must be explicit ordered attempt counts')
    if type(x['min_request_interval_seconds']) not in (int, float) or not 0 <= x['min_request_interval_seconds'] <= 60:
        raise ValueError('explicit bounded dispatch spacing required')
    if c['api_mode'] == 'real':
        if c['api_concurrency'] != 1:
            raise ValueError('safe fallback permits one generation worker only')
        from . import state_a, routing_state_a
        b = x['state_binding']
        if not isinstance(b, dict) or b != {'version':state_a.VERSION, 'spec_sha256':state_a.SPEC_SHA256,
                'abi':routing_state_a.ABI, 'history_extension_delivered':True}:
            raise ValueError('frozen delivered state binding missing or changed')
        if state_a.VERSION == 'common-state-a-v2':
            raise ValueError('the current ten-field delivery lacks the required per-H history extension')
        verify_client(c)
        a = x['account_exclusion']
        if (not isinstance(a, dict) or set(a) != {'scope','run_id','valid_until','confirmation'}
                or a['scope'] != 'all_devices_sharing_account' or a['run_id'] != x['run_id']
                or not isinstance(a['confirmation'], str) or not a['confirmation'].strip()
                or type(a['valid_until']) not in (int,float) or not math.isfinite(a['valid_until'])
                or not x['account_gate']):
            raise ValueError('external all-device account exclusion confirmation required')


def verify_client(c):
    from fjsp_usage.research_real.real_transport import WIRE_VERSION
    from heuristic_design.llm.strict_nonstream import POLICY
    x = c['execution_contract']['client_binding']
    if not isinstance(x, dict) or set(x) != {'wire_version','caller_policy','files','provider'}:
        raise ValueError('frozen V5 client identity required')
    if x['wire_version'] != WIRE_VERSION or x['caller_policy'] != POLICY or x['provider'] != c['provider'] or c['provider']['stream_response'] is not False:
        raise ValueError('client/provider differs from the admitted V5 path')
    root = Path(__file__).resolve().parents[3]
    required = {'code/fjsp_usage/research_real/real_transport.py', 'code/heuristic_design/llm/strict_nonstream.py'}
    if set(x['files']) != required or any(sha(root/k) != v for k,v in x['files'].items()):
        raise ValueError('bound common client bytes changed')


def resources(c):
    requested = c['execution_contract']['allocated_cpus']
    if os.environ.get('SLURM_JOB_ID'):
        actual = int(os.environ['SLURM_CPUS_PER_TASK'])
        if os.environ.get('SLURM_NTASKS', '1') != '1':
            raise ValueError('one controller task per run required')
    else:
        actual = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count()
    if actual is None or requested > actual:
        raise ValueError('configured resources exceed actual allocation')
    if any(os.environ.get(k) != '1' for k in THREAD_ENV):
        raise ValueError('numerical-library threads must be set to one before Python imports')
    return {'configured_cpus':requested, 'actual_cpus':actual,
            'evaluation_workers':c['evaluation_concurrency'], 'api_workers':c['api_concurrency'],
            'controller_cpus_reserved':1, 'staged_waves':True,
            'threads':{k:os.environ[k] for k in THREAD_ENV}}



def drain_bound(c, count):
    width=max(c['api_concurrency'],c['evaluation_concurrency'])
    api=(c.get('provider') or {}).get('total_timeout',0)
    spacing=c['execution_contract']['min_request_interval_seconds']
    return (math.ceil(width/c['api_concurrency'])*api + width*spacing
            + math.ceil(width/c['evaluation_concurrency'])*(count*c['instance_timeout_seconds']+2) + 5)

def bind_protocol(p):
    c = p['config']; x = c['execution_contract']
    bound = drain_bound(c, len(p['instances']))
    if x['drain_seconds'] < bound:
        raise ValueError('drain must cover API deadline + full declared evaluation + lifecycle grace')
    p.update(objective='mean((raw_cost-reference)/reference); minimize J; internal fitness=-J',
             selection='internal -J descending, fixed id ascending; original parent-coverage survival',
             state_history_delivery=x['state_binding'], drain_bound_seconds=bound,
             run_id=x['run_id'], group=x['group'], initialization='fixed N slots, no automatic refill',
             generation_budget='exact attempt prefix; invalids and duplicates consume attempts',
             source_cost=x['source_cost'])
    import subprocess
    root = Path(__file__).resolve().parents[3]
    if (root/'.git').exists():
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
        branch=subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip()
    else:
        release=read(root/'release.json');commit=release['commit'];branch=release['branch']
    p['git'] = {'commit':commit,'branch':branch,
                'runtime_source_sha256':digest(p['source_files']),
                'note':'source manifest binds exact bytes including any uncommitted runtime changes'}


def check_checkpoint(directory,p,s):
    clock = directory/'Run_clock.json'
    if s.get('clock_sha256') and (not clock.exists() or sha(clock) != s['clock_sha256']):
        raise ValueError('original cumulative deadline missing/changed; never reset')
    if clock.exists() and not s.get('clock_sha256'):
        raise ValueError('uncommitted clock; investigate without resetting')
    if s['phase'] == 'blocked' or s.get('hard_api_stop') or (directory/'Stop.json').exists():
        raise ValueError('blocked/unknown run requires investigation; no automatic replay')
    for t in s['tasks'].values():
        if t.get('send_state') == 'unknown':
            raise ValueError('unknown send retained; never replay')


def start_segment(directory,p,s):
    c=p['config']; x=c['execution_contract']; now=time.time()
    resource_receipt=resources(c)
    if 'clock_sha256' not in s:
        write(directory/'Run_clock.json', {'started_at':now,'deadline':now+x['window_seconds']})
        s['clock_sha256']=sha(directory/'Run_clock.json')
        from .evolution_v1 import save
        save(directory,s)
    if now >= read(directory/'Run_clock.json')['deadline']:
        raise ValueError('original calendar deadline expired; resume does not extend it')
    if c['api_mode']=='real':
        if x['account_exclusion']['valid_until'] < read(directory/'Run_clock.json')['deadline']:
            raise ValueError('account exclusion does not cover original calendar window')
        gate=Path(x['account_gate']).resolve();gate.mkdir(parents=True,exist_ok=True)
        fd=os.open(gate/'generation.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as f:
            json.dump({'run_id':x['run_id'],'protocol':s['identity'],'directory':str(directory)},f)
        registry=gate/('run-'+x['run_id']+'.json')
        identity={'directory':str(directory),'protocol':s['identity']}
        if registry.exists():
            if read(registry)!=identity:raise ValueError('run identity already claimed elsewhere; no budget reset')
        else:
            fd=os.open(registry,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as f:json.dump(identity,f)
    write(directory/'segments'/f'{time.time_ns()}.json', {'started_at':now,
        'segment_deadline':now+x['segment_seconds'],'original_deadline':read(directory/'Run_clock.json')['deadline'],
        'resources':resource_receipt,'host':socket.gethostname(),
        'slurm':{k:os.environ.get(k) for k in ('SLURM_JOB_ID','SLURM_ARRAY_JOB_ID','SLURM_ARRAY_TASK_ID','SLURM_CPUS_PER_TASK')},
        'scope':'execution segment wall clock, excludes queue and paused time'})
    s['segment_started_at']=now
    s['segment_started_monotonic']=time.monotonic()


def deadline_pause(directory,p,s):
    x=p['config']['execution_contract'];now=time.time()
    mono=time.monotonic()-s['segment_started_monotonic']
    if abs((now-s['segment_started_at'])-mono)>2:
        s.update(phase='paused',pause_reason='clock_or_suspend_gap_after_settled_batch')
        return True
    if now+x['drain_seconds'] >= min(read(directory/'Run_clock.json')['deadline'],s['segment_started_at']+x['segment_seconds']):
        s.update(phase='paused',pause_reason='drain_before_original_or_segment_deadline')
        return True
    return False


def bound_batch(batch,s,c):
    if batch[0]['stage']!='evolution':return batch
    next_mark=next((v for v in c['execution_contract']['milestone_attempts'] if v>s['generation_requests']),c['generation_request_cap'])
    return batch[:min(next_mark-s['generation_requests'],c['generation_request_cap']-s['generation_requests'])]


def settle_api(s,p,tasks,replies):
    if p['config']['api_mode']!='real':return
    from fjsp_usage.research_real.attempt_budget import failure_policy
    for t in tasks:
        r=replies[t['id']];v=r.get('value') if r.get('ok') else None
        if not isinstance(v,dict):
            t.update(status='unknown_send',send_state='unknown')
            raise RuntimeError('request worker failed without a send receipt; reservation retained')
        m=v.get('metadata') or {}
        state='confirmed' if v.get('sent') else m.get('send_status')
        # A V5 pre-send failure has observed a stage before http_send. Missing
        # audit or http_send without confirmation is intentionally ambiguous.
        if state not in ('confirmed','unknown'):
            state='not_sent' if m.get('failure_stage') in ('preflight','dns','connect','tls','prepare','connection') or m.get('connection_phase') in ('connecting','dns','tls') else 'unknown'
        t['send_state']=state
        t['usage']=v.get('usage');t['actual_cost']=None
        t['http_status']=m.get('http_status');t['failure_stage']=m.get('failure_stage')
        if state=='unknown':
            t['status']='unknown_send'
            raise RuntimeError('unknown physical send; retain reservation and prohibit replay')
        if v.get('text') is not None:
            t['api_outcome']='accepted';s['transport_failure_streak']=0
        else:
            temporary,reason,permanent=failure_policy(v.get('error',''),m,v.get('error_type',''))
            t['api_outcome']='response_rejected' if m.get('http_status')==200 else 'transport_failed'
            t['api_failure_policy']=reason
            s['transport_failure_streak']=s.get('transport_failure_streak',0)+1
            if permanent or m.get('caller_hard_stop') or not temporary:
                s.update(phase='paused',pause_reason='API hard error: '+reason,hard_api_stop=True)
            elif s['transport_failure_streak']>=3:
                s.update(phase='paused',pause_reason='three consecutive transport failures; no retry')


def pace(c):
    if c['api_mode']!='real' or c.get('execution_contract') is None:return
    x=c['execution_contract'];path=Path(x['account_gate'])/'last_dispatch.json'
    last=read(path)['reserved_at'] if path.exists() else 0
    delay=last+x['min_request_interval_seconds']-time.time()
    if delay>0:time.sleep(delay)
    write(path,{'reserved_at':time.time(),'run_id':x['run_id']})


def after_batch(directory,p,s):
    from .execution_export import export
    export(directory,p,s)
    n=s['generation_requests']
    if n in p['config']['execution_contract']['milestone_attempts']:
        write(directory/f'milestones/attempt-{n:06d}.json',{'protocol':s['identity'],
              'evolution_attempts':n,'checkpoint':s,'champion':champion(s),
              'note':'settled prefix snapshot; resume only from live original checkpoint'})


def champion(s):
    rows=[t for t in s['tasks'].values() if t.get('valid') and t['status']=='completed']
    return sorted(rows,key=lambda t:(-t['fitness'],t['id']))[0] if rows else None


def finish_segment(directory,p,s,normal):
    from .execution_export import export
    export(directory,p,s)
    if p['config']['api_mode']=='real' and normal and s['phase']!='blocked':
        lock=Path(p['config']['execution_contract']['account_gate'])/'generation.lock'
        if lock.exists() and read(lock)['protocol']==s['identity']:lock.unlink()


def _mock_worker(send,task,p):
    """Synthetic cost receipt in a real worker process; no constructor is used."""
    import resource
    import sys
    def deny(*a,**k):raise AssertionError('Mock worker forbids network and real solvers')
    socket.socket.connect=deny;socket.create_connection=deny
    from heuristic_design.problems import routing_fixtures
    routing_fixtures.solve=deny
    try:
        from .evolution_v1 import mock_evaluate
        value=mock_evaluate({**task,'_mock_child':True},p)
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        value['mock_worker']={'pid':os.getpid(),'started_at':time.time(),
            'peak_rss_bytes':int(rss if sys.platform=='darwin' else rss*1024),
            'real_solves':0,'model_requests':0}
        time.sleep(.03)
        value['mock_worker']['finished_at']=time.time()
        send.send(value)
    finally:send.close()


def mock_process_receipt(task,p):
    import multiprocessing as mp
    ctx=mp.get_context('spawn');receive,send=ctx.Pipe(duplex=False)
    worker=ctx.Process(target=_mock_worker,args=(send,task,p))
    worker.start();send.close()
    try:
        if not receive.poll(15):raise RuntimeError('synthetic receipt worker timed out')
        value=receive.recv();worker.join(2)
        if worker.exitcode!=0:raise RuntimeError('synthetic receipt worker exit not certified')
        return value
    finally:
        receive.close()
        if worker.is_alive():worker.terminate();worker.join(2)
