"""Bounded request admission for two independent existing coordinators.

The batch retains the original account lease. Inner per-run leases are writer
guards, not account limiters. No search loop, provider, retry, or solver here.
"""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import time
from heuristic_design.core.storage import read, write, sha, digest
from experiments.triad.concurrency_probe import Gate as ProbeGate, claim, stop, filesystem_check

VERSION = 'two-independent-searches-request-admission-v1'


def durable(path,value):
    """Persist admission before permitting a wire call; no budget rollback."""
    path=Path(path);pending=path.with_suffix('.pending')
    with pending.open('w') as f:
        json.dump(value,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(pending,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def load(path):
    path=Path(path).resolve(); m=read(path)
    if m['mode'] not in ('mock','real'):raise ValueError('explicit Mock/real admission identity required')
    if m['version']!=VERSION or m['max_active_searches']!=2 or m['global_API_width']!=1:
        raise ValueError('this release supports at most two searches and global API1 only')
    rows=m['members']
    if len(rows)!=2 or len({r['run_id'] for r in rows})!=2 or len({r['seed'] for r in rows})!=2:
        raise ValueError('two distinct run IDs and independent seeds required')
    if len({r['run_dir'] for r in rows})!=2 or any(r['group']=='fjsp-u' and r['seed']==501 for r in rows):
        raise ValueError('distinct directories required; existing U501 is read-only')
    if any(r['group'] not in ('fjsp-u','fjsp-eoh') or r['seed'] not in (502,503) or Path(r['run_dir']).name!=r['run_id'] for r in rows):raise ValueError('this FJSP release selects new independent seeds502/503 only')
    if m['mode']=='real':
        expected=read(Path(__file__).resolve().parents[2]/'preparations/cluster-concurrency-20261114/phase1/Probe.pending.json')['account_gate']
        if m['account_gate']!=expected:raise ValueError('retain the original common account gate; no independent account locks')
    if m['total_request_cap']!=sum(r['request_cap'] for r in rows):raise ValueError('aggregate original cap differs')
    for row in rows:
        c=read(row['config'])
        if sha(row['config'])!=row['config_sha256'] or c['mode']!=m['mode'] or c['api_attempt_cap']!=row['request_cap'] or c['search_seed']!=row['seed'] or c.get('shared_manifest')!=str(path):raise ValueError('member configuration/mode/cap/seed binding changed')
    if not 0<=m['min_request_interval_seconds']<=60:raise ValueError('invalid global pacing')
    if type(m['queue_wait_seconds']) is not int or not 1<=m['queue_wait_seconds']<=600:raise ValueError('bounded positive queue wait required')
    return m


def binding(path,directory,config_path):
    path=Path(path).resolve(); m=load(path); directory=Path(directory).resolve()
    row=next(r for r in m['members'] if Path(r['run_dir']).resolve()==directory)
    if sha(config_path)!=row['config_sha256']:raise ValueError('shared member configuration changed')
    c=read(config_path)
    if c.get('shared_manifest')!=str(path):raise ValueError('configuration missing original shared execution binding')
    if c['search_seed']!=row['seed'] or c['api_attempt_cap']!=row['request_cap'] or c['group']!=row['group']:
        raise ValueError('member seed/budget/group mismatch')
    if Path(c['account_gate']).resolve()!=path.parent/'run-gates'/row['run_id']:
        raise ValueError('inner writer gate must belong to this admitted batch')
    return {'version':VERSION,'manifest':str(path),'sha256':sha(path),'run_id':row['run_id'],'config_sha256':row['config_sha256']}


def attach(directory,b):
    d=Path(directory); value=attachment(directory,b)
    path=d/'Shared_execution.json'
    if path.exists():
        if read(path)!=value:raise ValueError('shared execution attachment changed; no rebind')
    else:claim(path,value)


def attachment(directory,b):
    root=Path(__file__).resolve().parents[2]
    return {**b,'protocol_sha256':sha(Path(directory)/'Protocol.json'),'adapter_sha256':sha(__file__),
      'execution_sources':{str(p.relative_to(root)):sha(p) for p in sorted((root/'experiments/triad').glob('*.py'))}}


def verify_attachment(directory,b):
    expected=attachment(directory,b)
    if read(Path(directory)/'Shared_execution.json')!=expected:raise ValueError('original shared execution attachment differs')
    if sha(b['manifest'])!=b['sha256']:raise ValueError('original shared manifest changed')


def activate(path):
    """Explicit manual activation only; never take over a live/unknown old lease."""
    path=Path(path).resolve(); m=load(path); parent=Path(m['account_gate']); lease=parent/'generation.lock'
    if (path.parent/'Activation.json').exists():raise FileExistsError('already activated/reserved; inspect, never reactivate')
    if m['mode']=='real' and (not m.get('account_exclusion') or m['account_exclusion'].get('valid_until',0)<=time.time()):
        raise PermissionError('fresh all-device exclusion required')
    identity={'protocol':'SHARED:'+sha(path),'batch':str(path),'version':VERSION}
    claim(path.parent/'Activation.json',{'state':'reserved','account_lease':str(lease),'identity':identity})
    claim(lease,identity)
    claim(path.parent/'gate/ledger.json',{'version':VERSION,'manifest_sha256':sha(path),'next_ticket':0,'requests':{},'active':{},'jobs':{},'events':[],'peak':0,'last_sent_at':0})
    write(path.parent/'Activation.json',{'state':'active','account_lease':str(lease),'identity':identity})


class Admission:
    def __init__(self,b,deadline=None):
        self.b=b; self.path=Path(b['manifest']); self.m=load(self.path); self.folder=self.path.parent/'gate'
        self.member=b['run_id']; self.deadline=deadline or time.time()+self.m['queue_wait_seconds']
        self.row=next(r for r in self.m['members'] if r['run_id']==self.member)

    def verify(self):
        if sha(self.path)!=self.b['sha256']:raise ValueError('shared manifest identity changed')
        if read(Path(self.m['account_gate'])/'generation.lock').get('protocol')!='SHARED:'+self.b['sha256']:
            raise PermissionError('original whole-account batch lease missing/different')
        if self.m['mode']=='real' and self.m['account_exclusion']['valid_until']<time.time():
            stop(self.folder,'account exclusion expired');raise PermissionError('account exclusion expired; no renewal')

    @contextmanager
    def transaction(self):
        # Reuse the already tested exclusive writer; timeout never steals it.
        g=ProbeGate(self.folder,1,time.time()+10,0)
        with g.transaction():
            self.verify(); s=read(self.folder/'ledger.json')
            if s['manifest_sha256']!=self.b['sha256']:raise ValueError('shared ledger identity differs')
            before=digest(s)
            yield s
            if digest(s)!=before:durable(self.folder/'ledger.json',s)

    @staticmethod
    def event(s,event,**values):
        s['events'].append({'sequence':len(s['events']),'event':event,'at':time.time(),**values})

    def acquire(self,key):
        started=time.monotonic(); uid=digest({'member':self.member,'key':key})
        with self.transaction() as s:
            if (self.folder/'STOP.json').exists():raise RuntimeError('shared STOP: no new requests')
            if self.member not in s['jobs']:raise RuntimeError('request without active admitted search')
            if uid in s['requests']:raise RuntimeError('attempt already reserved; never replay or refund')
            if sum(r['member']==self.member for r in s['requests'].values())>=self.row['request_cap'] or len(s['requests'])>=self.m['total_request_cap']:
                raise RuntimeError('original member/aggregate request cap exhausted')
            s['requests'][uid]={'member':self.member,'key':key,'ticket':s['next_ticket'],'state':'waiting','reserved_at':time.time()}
            s['next_ticket']+=1; self.event(s,'waiting',uid=uid,member=self.member)
        while True:
            if time.time()>=self.deadline:
                stop(self.folder,'bounded queue wait ended; reservations retained, no replay')
                raise TimeoutError('request admission wait exceeded; no refund')
            with self.transaction() as s:
                if (self.folder/'STOP.json').exists():raise RuntimeError('shared STOP while waiting; reservation retained')
                waiting=[(v['ticket'],k) for k,v in s['requests'].items() if v['state']=='waiting']
                first=min(waiting)[1] if waiting else None
                if not s['active'] and first==uid:
                    s['active'][uid]=self.member; s['peak']=max(s['peak'],len(s['active']))
                    s['requests'][uid].update(state='admitted',wait_seconds=time.monotonic()-started)
                    self.event(s,'admitted',uid=uid,member=self.member);return uid
            time.sleep(.1)

    def sent(self,uid):
        with self.transaction() as s:
            r=s['requests'][uid]
            if s['active'].get(uid)!=self.member or r['state']!='admitted':raise RuntimeError('send without owned permit')
            if (self.folder/'STOP.json').exists():raise RuntimeError('STOP before physical dispatch')
            r.update(state='sent',sent_at=time.time(),pacing_seconds=self.m['min_request_interval_seconds']);s['last_sent_at']=r['sent_at'];self.event(s,'sent',uid=uid,member=self.member)

    def settled(self,uid,value,wire_seconds):
        with self.transaction() as s:
            r=s['requests'][uid]
            if s['active'].get(uid)!=self.member or r['state']!='sent':raise RuntimeError('response without known owned send')
            r.update(state='completed',finished_at=time.time(),usage=value.get('usage'),wire_seconds=wire_seconds)
            del s['active'][uid];self.event(s,'settled',uid=uid,member=self.member)

    def failed(self,uid,error):
        # No classification releases a failed permit in this conservative first release.
        stop(self.folder,'first transport/admission failure; shared sends stopped; inspect retained reservation')
        with self.transaction() as s:
            s['requests'][uid].update(state='failed_or_unknown',error_type=type(error).__name__,send_state=(getattr(error,'metadata',{}) or {}).get('send_status','unknown'),finished_at=time.time())
            self.event(s,'failed_or_unknown',uid=uid,member=self.member)

    @contextmanager
    def session(self,directory):
        verify_attachment(directory,self.b)
        d=Path(directory); token=str(os.getpid())+'-'+str(time.time_ns()); registered=False
        try:
            with self.transaction() as s:
                if (self.folder/'STOP.json').exists():raise RuntimeError('shared STOP retained; no automatic recovery')
                if self.member in s['jobs'] or len(s['jobs'])>=2:raise RuntimeError('active/unknown search lease retained')
                s['jobs'][self.member]={'token':token,'pid':os.getpid(),'host':__import__('socket').gethostname()}
                self.event(s,'search_started',member=self.member);registered=True
            if self.m.get('require_initial_preflight'):
                role=next(i for i,r in enumerate(self.m['members']) if r['run_id']==self.member)
                preflight=self.path.parent/'preflight';preflight.mkdir(exist_ok=True)
                if not (preflight/f'fs-pass-{role}.json').exists():
                    filesystem_check(preflight,role,time.time()+self.m['queue_wait_seconds'])
            yield
        finally:
            if registered:
                cp=read(d/'checkpoint.json');safe=cp['phase'] in ('completed','paused','initialization_incomplete','expired') and not (d/'Stop.json').exists()
                with self.transaction() as s:
                    safe=safe and not any(v==self.member for v in s['active'].values()) and not any(v['member']==self.member and v['state']!='completed' for v in s['requests'].values())
                    if safe and s['jobs'].get(self.member,{}).get('token')==token:
                        del s['jobs'][self.member];self.event(s,'search_settled',member=self.member,phase=cp['phase'])
                    else:stop(self.folder,'search ended without certified settlement; keep job/request reservations')


class GuardedTransport:
    """Wrap the actual V5 dispatch, releasing its permit before CPU evaluation."""
    def __init__(self,inner,admission):
        self.inner=inner;self.admission=admission;self.config=inner.config
        self.identity=digest({'transport':inner.identity,'shared':admission.b,'version':VERSION})
    def __getattr__(self,name):return getattr(self.inner,name)
    def preflight(self,prompt):return self.inner.preflight(prompt)
    def dispatch(self,key,prompt,*,kind,on_sent):
        verify_attachment(self.admission.row['run_dir'],self.admission.b)
        try:uid=self.admission.acquire(key)
        except BaseException as error:
            error.metadata={**(getattr(error,'metadata',{}) or {}),'send_status':'not_sent','failure_stage':'shared_admission'}
            raise
        started=time.monotonic()
        inner_started=False
        try:
            # Hold the FREE permit, then wait using monotonic time. This is
            # conservative inter-send spacing even when node wall clocks differ.
            time.sleep(self.admission.m['min_request_interval_seconds'])
            self.admission.verify()
            if (self.admission.folder/'STOP.json').exists():raise RuntimeError('shared STOP before wire dispatch')
            clock=Path(self.admission.row['run_dir'])/'Run_clock.json'
            c=read(self.admission.row['config'])
            reserve=c['provider']['total_timeout']+c['instance_timeout_seconds']*c['instance_count']+5
            if clock.exists() and time.time()+reserve>read(clock)['deadline']:
                raise TimeoutError('original calendar window cannot cover dispatch and evaluation after waiting')
            def sent():self.admission.sent(uid);on_sent()
            inner_started=True
            value=self.inner.dispatch(key,prompt,kind=kind,on_sent=sent)
            self.admission.settled(uid,value,time.monotonic()-started);return value
        except BaseException as error:
            if not inner_started:error.metadata={**(getattr(error,'metadata',{}) or {}),'send_status':'not_sent','failure_stage':'shared_admission'}
            self.admission.failed(uid,error);raise


def adapter(b):
    from experiments.triad.runtime import Adapter
    class AdmittedAdapter(Adapter):
        def check_run(self,d):
            p=super().check_run(d);verify_attachment(d,b);return p
        def transport(self,p):return GuardedTransport(super().transport(p),Admission(b))
        def task_context(self,d,s,p,task,index):
            clock=Path(d)/'Run_clock.json'
            if clock.exists() and time.time()+p['config']['resources']['drain_seconds']>=read(clock)['deadline']:
                s.update(phase='expired',pause_reason='shared queue/evaluation drain before original deadline');return None,[]
            return super().task_context(d,s,p,task,index)
    return AdmittedAdapter()


@contextmanager
def frozen_hooks(b,directory):
    """Process-local transport adapter; frozen U coordinator and batch order unchanged."""
    from unittest.mock import patch
    from heuristic_design.core import evolution_v1 as engine
    from heuristic_design.llm import routing_transport
    verify_attachment(directory,b); admission=Admission(b)
    state=read(Path(directory)/'checkpoint.json')
    if any(t['stage']=='initialization' and t['status']=='planned' for t in state['tasks'].values()):
        raise PermissionError('orphaned planned initialization task; no skip, repair or replay in this adapter')
    original=routing_transport.StrictNonstreamTransport
    original_mock=engine.mock_generate
    def factory(c):return GuardedTransport(original(c),admission)
    def mock(task,prompt,c,members):
        class Mock:
            config=None;identity='frozen-U-original-mock'
            def dispatch(self,key,prompt,*,kind,on_sent):
                on_sent();return {'text':original_mock(task,prompt,c,members)}
        return GuardedTransport(Mock(),admission).dispatch(task['request_key'],prompt,kind='U',on_sent=lambda:None)['text']
    with patch.object(routing_transport,'StrictNonstreamTransport',factory),patch.object(engine,'mock_generate',mock),admission.session(directory):
        yield
