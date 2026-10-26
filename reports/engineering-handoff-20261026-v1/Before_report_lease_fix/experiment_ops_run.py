"""Execution glue only: old prompts, AttemptJournal, rank selection and T30.

Unknown reservations never become free retries; historical controllers untouched.
"""
from dataclasses import asdict
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import signal
from statistics import fmean
import subprocess
import sys
import time

from tools import experiment_ops as o
from tools.experiment_ops_prompts import build
from fjsp_usage.research.candidates import parse_response,CandidateError
from fjsp_usage.research.evolution import select_parents,_tuple_tree
from fjsp_usage.research.sets import ranked
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.research_real.attempt_budget import AttemptJournal,CIRCUIT_VERSION
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from fjsp_usage.usage_v2.access import WireRecorder
from fjsp_usage.baseline_a.validation import validate_result


class ClientConfig:
    """Minimal protocol adapter; avoids old four-arm SearchConfig's 10-slot rule.

ProviderConfig and AttemptJournal still perform their original validations.
No financial/account fields or account client are installed.
"""
    def __init__(self,p):
        c=p['config'];self.provider=ProviderConfig(**c['provider'])
        self.mode='real' if c['api_mode']=='real' else 'synthetic'
        self.real_requests_authorized=c['real_requests_authorized']
        self.total_request_cap=p['budgets']['logical_generation']
        self.request_budget={'version':CIRCUIT_VERSION,'logical_candidate_cap':self.total_request_cap,
            'api_attempt_cap':c['api_attempt_cap'],'per_candidate_attempt_cap':c['per_candidate_attempt_cap'],
            'retry_backoff_seconds':[2]*(c['per_candidate_attempt_cap']-1),'protocol_error_circuit_threshold':3}
    def payload(self):
        return {'provider':asdict(self.provider),'mode':self.mode,'real_requests_authorized':self.real_requests_authorized,
                'total_request_cap':self.total_request_cap,'request_budget':self.request_budget}
    def check_dispatch(self):
        if self.mode=='real' and not self.real_requests_authorized:raise PermissionError('configuration does not authorize real API')


class MockTransport:
    def __init__(self,p):
        self.p=p;self.config=ClientConfig(p);self.identity=o.digest({'mock_fixture_version':1,'config':self.config.payload()});self.secret=''
    def redact(self,text):return text
    def preflight(self,prompt):
        if len(prompt.encode())>self.config.provider.max_prompt_bytes:raise ValueError('mock prompt too long')
    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        on_sent();time.sleep(self.p['config']['mock_delay_seconds'])
        n=int(o.digest(key)[:4],16)
        value=o.candidate({'id':'MOCK_NOT_LLM','alpha':(.1,.2,.3,.4)[n%4]} if self.p['config']['space']=='h01'
                          else {'id':'MOCK_NOT_LLM','member':n%10},self.p['config']['space'])
        return {'text':'{MOCK deterministic engineering fixture, not LLM-generated.}\n```python\n'+value['code']+'```',
                'usage':{'input_tokens':0,'output_tokens':0},'metadata':{'model':'MOCK_OFFLINE_NOT_LLM','mock':True}}


class DeadlineTransport:
    def __init__(self,wire,deadline):
        self.wire=wire;self.deadline=deadline;self.directory=wire.directory;self.identity=wire.identity;self.redact=wire.redact
    def preflight(self,prompt):
        if time.time()>=self.deadline:raise ValueError('persistent deadline reached before API attempt')
        self.wire.preflight(prompt)
    def dispatch(self,*a,**k):return self.wire.dispatch(*a,**k)


def ledger(directory,s,p):
    if s['identity']!=o.sha(directory/'Protocol.json'):raise ValueError('checkpoint protocol identity mismatch')
    clock=directory/'Run_clock.json'
    if s.get('clock_sha256'):
        if not clock.exists() or o.sha(clock)!=s['clock_sha256']:raise ValueError('persistent clock missing/changed; never reset')
    elif clock.exists():raise ValueError('uncommitted clock receipt; preserve, do not reset')
    plan=o.read(directory/'Tasks.json')
    if set(s['tasks'])!={t['id'] for t in plan[:s['cursor']]}:raise ValueError('unknown/uncommitted task reservation; preserve lock and evidence')
    if len(s['tasks'])>len(plan):raise ValueError('task budget exceeded')
    for key,e in s['evaluations'].items():
        if e['status']!='completed':raise ValueError('unknown evaluation reservation; no automatic replay')
        path=directory/e['path']
        if not path.resolve().is_relative_to(directory) or o.sha(path)!=e['sha256']:raise ValueError('result path/hash changed')
        validate_result(o.read(path),p['instances'],'modern')
    n=len(s['evaluations'])*len(p['instances'])
    if n>p['budgets']['max_program_instances']:raise ValueError('evaluation budget exceeded')
    jpath=directory/'API_attempts.json'
    if jpath.exists():
        j=o.read(jpath)
        if j.get('halt_reason'):raise ValueError('persistent API Stop: '+j['halt_reason'])
        if any(a['status'] not in ('completed','failed') for a in j['api_attempts'].values()):raise ValueError('unknown API attempt; do not resend')


def evaluate(directory,s,p,candidate):
    key=candidate.key
    if key in s['evaluations']:return o.read(directory/s['evaluations'][key]['path']),True
    if (len(s['evaluations'])+1)*len(p['instances'])>p['budgets']['max_program_instances']:raise ValueError('evaluation cap')
    folder=directory/'evaluations'/key;folder.mkdir(parents=True,exist_ok=False)
    s['evaluations'][key]={'status':'reserved'};o.write(directory/'checkpoint.json',s)
    paths=[directory/r['relative_path'] for r in p['instances']]
    instances=[o.certified.s.v2.load_instance(path) for path in paths]
    members=[o.checked_candidate(r['candidate'],'h') for r in o.read(directory/'H_frozen.json')['members']]
    payload={'folder':str(folder),'binding':p,'candidate':asdict(candidate),'train_paths':[str(path) for path in paths]}
    o.write(folder/'Input_receipt.json',{'candidate':asdict(candidate),'instances':p['instances'],'protocol_sha256':s['identity']})
    expected={**p['source_files'],**p['protected_files']};before={k:o.sha(o.ROOT/k) for k in expected};beg=time.monotonic()
    rows,failure,life=o.certified.collect(mp.get_context('spawn'),o.certified.worker,payload,members,instances,
        [r['file'] for r in p['instances']],30,(1,) if p['config']['space']=='h01' else (0,1),lambda r:o.write(folder/'lifecycle.json',r))
    result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
            'instances':rows,'total_instances':len(instances),'primary_evaluation_seconds':time.monotonic()-beg,**(failure or {})}
    o.write(folder/'raw_result.json',result)
    boundary=o.certified.certify(result,dict(before=o.read(folder/'before.json') if (folder/'before.json').exists() else None,
        after=o.read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
        expected_identity=o.read(directory/'Solver_identity.json')['identity'],expected_files=expected,start_files=before,
        end_files={k:o.sha(o.ROOT/k) for k in expected},worker_failure=(folder/'worker_failure.json').exists()))
    o.write(folder/'boundary.json',boundary)
    if boundary['decision']=='stop':raise ValueError('certification Stop: '+boundary['reason'])
    validate_result(result,p['instances'],'modern');result['boundary']=boundary;o.write(folder/'result.json',result)
    s['evaluations'][key]={'status':'completed','path':str((folder/'result.json').relative_to(directory)),'sha256':o.sha(folder/'result.json')}
    o.write(directory/'checkpoint.json',s);return result,False


def pause_sequence(directory):
    return o.read(directory/'Pause_request.json')['sequence'] if (directory/'Pause_request.json').exists() else 0


def stop(directory):
    o.check_run(directory);s=o.read(directory/'checkpoint.json')
    if s['phase'] in ('completed','stopped','expired'):raise ValueError('already terminal; no stop action')
    record={'sequence':pause_sequence(directory)+1,'requested_at':time.time(),'action':'pause_at_candidate_boundary'}
    (directory/'control').mkdir(exist_ok=True);o.write(directory/'control'/f"pause_{record['sequence']:04d}.json",record)
    o.write(directory/'Pause_request.json',record)
    return {'requested':True,'instruction':'wait for phase=paused and writer lock removal; never kill worker'}


def start(directory,*,resume=False,allow_api=False,background=False):
    p=o.check_run(directory);s=o.read(directory/'checkpoint.json');ledger(directory,s,p)
    if (directory/'.execution.lock').exists() or (directory/'Stop.json').exists():raise ValueError('lock/Stop present; no automatic cleanup or replay')
    if s['phase']!=('paused' if resume else 'prepared'):raise ValueError('run requires prepared; resume requires safely paused checkpoint')
    if p['config']['api_mode']=='real':
        if not allow_api or not p['config']['real_requests_authorized']:raise PermissionError('real API requires config true AND explicit --allow-api on run/resume')
        key_env=p['config']['provider']['api_key_env']
        if key_env and not os.environ.get(key_env):raise ValueError('credential environment variable is absent; key not printed')
    if (directory/'Run_clock.json').exists():
        clock=o.read(directory/'Run_clock.json')
        if time.time()>=clock['deadline']:raise ValueError('original window expired; never reset/extend on resume')
    # Durable exclusive launch reservation closes the detach/start race.
    fd=os.open(directory/'.execution.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'state':'launch_reserved','pid':os.getpid()},f)
    s['pause_ack']=pause_sequence(directory) if resume else s['pause_ack']
    s['phase']='launching';o.write(directory/'checkpoint.json',s)
    o.write(directory/'Launch_authorization.json',{'protocol':s['identity'],'operation':'resume' if resume else 'run',
        'explicit_cli_allow_api':allow_api,'api_mode':p['config']['api_mode'],'at':time.time()})
    if background:
        env={**os.environ,'PYTHONPATH':str(o.ROOT/'code')+':'+str(o.ROOT),'PYTHONDONTWRITEBYTECODE':'1'}
        pid=o.certified.detach([sys.executable,'-B',str(o.ROOT/'experiments/tier2/manage.py'),'_work','--run-dir',str(directory)],directory/'Console.log',env=env)
        o.write(directory/'Launch_pid.json',{'pid':pid,'at':time.time(),'method':'existing detached session, SIGHUP ignore, file logs'})
        return {'pid':pid,'run_dir':str(directory),'note':'controller may exit; sleep/lid/logout/reboot are not guaranteed'}
    return work(directory)


def work(directory):
    p=o.check_run(directory);s=o.read(directory/'checkpoint.json');ledger(directory,s,p)
    auth=o.read(directory/'Launch_authorization.json')
    if s['phase']!='launching' or auth['protocol']!=s['identity'] or not (directory/'.execution.lock').exists():raise ValueError('work requires this run launch reservation')
    if p['config']['api_mode']=='real' and not auth['explicit_cli_allow_api']:raise PermissionError('no real launch acknowledgement')
    o.write(directory/'.execution.lock',{'pid':os.getpid(),'state':'running'})
    keep=None;normal=False;requested=[False]
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    signal.signal(signal.SIGINT,lambda *a:requested.__setitem__(0,True))
    signal.signal(signal.SIGTERM,lambda *a:requested.__setitem__(0,True))
    try:
        if not (directory/'Run_clock.json').exists():
            t=time.time();o.write(directory/'Run_clock.json',{'start':t,'deadline':t+p['config']['window_seconds']})
            s['clock_sha256']=o.sha(directory/'Run_clock.json');o.write(directory/'checkpoint.json',s)
        clock=o.read(directory/'Run_clock.json')
        if clock['deadline']!=clock['start']+p['config']['window_seconds']:raise ValueError('deadline changed')
        if sys.platform=='darwin':keep=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        o.write(directory/'Run_identity.json',{'pid':os.getpid(),'ppid':os.getppid(),'sid':os.getsid(0),'at':time.time()})
        journal=None
        if p['budgets']['logical_generation']:
            inner=MockTransport(p) if p['config']['api_mode']=='mock' else JsonCandidateTransport(ClientConfig(p))
            wire=WireRecorder(inner,directory/'wire_responses',verify=lambda:o.check_run(directory))
            journal=AttemptJournal(directory/'API_attempts.json',config=ClientConfig(p),context=s['identity'],phase='operations/'+s['identity'],
                transport=DeadlineTransport(wire,clock['deadline']))
        members=[o.checked_candidate(r['candidate'],'h') for r in o.read(directory/'H_frozen.json')['members']]
        plan=o.read(directory/'Tasks.json');rng=random.Random(p['config']['search_seed'])
        if s.get('rng'):rng.setstate(_tuple_tree(s['rng']))
        s['phase']='running';o.write(directory/'checkpoint.json',s)
        for index in range(s['cursor'],len(plan)):
            o.check_run(directory);ledger(directory,s,p)
            if requested[0] or pause_sequence(directory)>s['pause_ack']:s['phase']='paused';break
            reserve=30*len(p['instances'])+5
            if plan[index]['stage']=='new':reserve+=p['config']['per_candidate_attempt_cap']*p['config']['provider']['total_timeout']+2
            if time.time()+reserve>clock['deadline']:s['phase']='expired';break
            task=plan[index];tid=task['id'];beg={'wall':time.time(),'monotonic':time.monotonic()}
            record={**task,'status':'reserved','started':beg,'valid':False,'fitness':None,'parents':[]}
            s['tasks'][tid]=record;o.write(directory/'checkpoint.json',s)
            c=None
            if task['stage']!='new':c=o.checked_candidate(task['candidate'],'U')
            else:
                if p['config']['type']=='evo':parents=select_parents(s['population'],p['config']['cross_parents'] if task['operator']=='CROSS' else 1,rng)
                elif p['config']['type']=='cross_ab':parents=[next(r for r in o.read(directory/'Parents.json') if r['id']==pid) for pid in task['parents']]
                else:parents=[]
                record['parents']=[r['id'] for r in parents];record['parent_keys']=[r['candidate']['key'] for r in parents]
                prompt=build(p['config'],task,parents,members);record['prompt']=prompt
                (directory/'prompts').mkdir(exist_ok=True);o.write(directory/'prompts'/(f'{index:05d}.json'),{'id':tid,'prompt':prompt})
                reply=journal.request(tid,prompt,kind='U');record['generation_status']=reply['status']
                if journal.data['halt_reason']:raise ValueError('API Stop: '+journal.data['halt_reason'])
                if reply['status']=='completed':
                    s['transport_failure_streak']=0
                    (directory/'responses').mkdir(exist_ok=True);o.write(directory/'responses'/f'{index:05d}.json',reply)
                    try:
                        c=parse_response(reply['text'],kind='U',interface_version=o.INTERFACE,member_count=10)
                        if p['config']['space']=='h01':c=o.h01.validate(c.code,c.description)
                    except CandidateError as exc:record['failure']='parse_or_constraint_error';record['error']=str(exc)
                else:
                    record['failure']='HTTP_or_transport_failure';s['transport_failure_streak']=s.get('transport_failure_streak',0)+1
            child=None
            if c:
                record['candidate']=asdict(c);record['AST_duplicate']=c.key in s['seen'];s['seen'][c.key]=tid
                result,cache=evaluate(directory,s,p,c);record.update(valid=result['valid'],fitness=result['fitness'],cache_hit=cache,evaluation_key=c.key)
                if result['valid']:
                    child={'id':tid,'candidate':asdict(c),'fitness':result['fitness'],'scores':[r['score'] for r in result['instances']]}
                else:record['failure']='evaluation_invalid'
            end={'wall':time.time(),'monotonic':time.monotonic()}
            if abs((end['wall']-beg['wall'])-(end['monotonic']-beg['monotonic']))>2:
                o.write(directory/'Clock_quarantine.json',{'task':tid,'before':beg,'after':end});raise ValueError('clock gap; preserve uncommitted evidence')
            if task['stage']=='p0' and child:s['population'].append(child);s['population']=ranked(s['population'])
            if task['stage']=='new' and p['config']['type']=='evo' and child and not record.get('AST_duplicate'):s['children'].append(child)
            last_gen_task=task.get('generation') is not None and (index+1==len(plan) or plan[index+1].get('generation')!=task['generation'])
            if last_gen_task:
                s['population']=ranked(s['population']+s['children'])[:p['config']['population_size']];s['children']=[];s['generation']+=1
                (directory/'populations').mkdir(exist_ok=True);o.write(directory/'populations'/f"P{s['generation']}.json",s['population'])
            record.update(status='completed',finished=end);s['cursor']+=1;s['rng']=rng.getstate()
            if index+1<len(plan) and plan[index+1]['stage']=='new' and p['config']['type']=='evo' and len(s['population'])!=p['config']['population_size']:
                raise ValueError('P0 incomplete; cannot fill/borrow parents or continue EVO')
            o.write(directory/'checkpoint.json',s)
            with (directory/'Events.jsonl').open('a') as f:f.write(json.dumps({'event':'task_committed','id':tid,'cursor':s['cursor'],'at':end['wall']})+'\n');f.flush();os.fsync(f.fileno())
            if s.get('transport_failure_streak',0)>=3:raise ValueError('three consecutive failed logical transports; Stop without refill')
        else:s['phase']='completed'
        o.write(directory/'checkpoint.json',s);normal=True
    except BaseException as exc:
        s['phase']='stopped';o.write(directory/'checkpoint.json',s)
        o.write(directory/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc),'at':time.time(),'automatic_retry':False})
    finally:
        if keep is not None:
            keep.terminate()
            try:keep.wait(timeout=2)
            except subprocess.TimeoutExpired:keep.kill();keep.wait()
        (directory/'end_receipts').mkdir(exist_ok=True)
        receipt={'phase':s['phase'],'cursor':s['cursor'],'at':time.time(),'caffeinate_cleaned':keep is not None,'lock_retained':not normal}
        o.write(directory/'end_receipts'/f'{time.time_ns()}.json',receipt);o.write(directory/'End_summary.json',receipt)
        if normal:(directory/'.execution.lock').unlink()
        from tools.experiment_ops_report import summary
        summary(directory,write_files=True)
    return {'phase':s['phase'],'cursor':s['cursor'],'run_dir':str(directory)}
