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
import multiprocessing
import stat
import math
import subprocess
from heuristic_design.core.storage import read, write, sha, digest
from experiments.triad.concurrency_probe import Gate as ProbeGate, claim, stop, filesystem_check, wait_file

VERSION = 'two-searches-six-groups-api1-v4'
EXPLORE = 'explore-light-v1'
INDEPENDENT = 'independent-seeds-v1'
BATCH_GATE_DIR = 'batch-gate'


def independent(m):return m.get('runtime_policy') == INDEPENDENT


def exploration(m):return m.get('runtime_policy') in (EXPLORE, INDEPENDENT)


def local_filesystem_probe(folder,role,deadline):
    claim(Path(folder)/f'participant-{role}.json',{'job_id':os.environ.get('SLURM_JOB_ID'),'pid':os.getpid(),'host':__import__('socket').gethostname(),'member':'filesystem-helper-only'})
    filesystem_check(folder,role,deadline)


def allocation_check(c):
    """Actual allocation and credential permission metadata only; never read the key."""
    if not os.environ.get('SLURM_JOB_ID','').isdigit():raise PermissionError('real execution requires a compute allocation')
    cpus=int(os.environ.get('SLURM_CPUS_PER_TASK','0'))
    def mib(value):
        if value is None:return None
        text=str(value).upper();factor=1
        if text.endswith(('K','M','G')):
            factor={'K':1/1024,'M':1,'G':1024}[text[-1]];text=text[:-1]
        return float(text)*factor
    memory=mib(os.environ.get('SLURM_MEM_PER_NODE'))
    if memory is None and os.environ.get('SLURM_MEM_PER_CPU'):memory=mib(os.environ['SLURM_MEM_PER_CPU'])*cpus
    if memory is None:
        job=os.environ['SLURM_JOB_ID']
        result=subprocess.run(['scontrol','-o','show','job',job],check=True,capture_output=True,text=True,timeout=15)
        fields=dict(word.split('=',1) for word in result.stdout.split() if '=' in word)
        if fields.get('JobId')==job and fields.get('JobState')=='RUNNING' and fields.get('NumNodes')=='1':
            memory=mib(fields.get('MinMemoryNode'))
            if memory is None and fields.get('MinMemoryCPU'):
                memory=mib(fields['MinMemoryCPU'])*int(fields['NumCPUs'])
    if cpus<c['resources']['cpus'] or memory is None or not math.isfinite(memory) or memory<c['resources']['memory_mib']:
        raise PermissionError('actual allocation CPU/memory evidence missing or insufficient; never export invented values')
    info=Path(c['credential_file']).lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:
        raise PermissionError('credential permission metadata invalid; no secret read')


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
    if m.get('runtime_policy') not in (None,EXPLORE,INDEPENDENT):raise ValueError('unknown runtime policy')
    if exploration(m) and m.get('require_initial_preflight') is not True:raise ValueError('exploration requires fresh allocation selfcheck')
    if independent(m):
        from .batch_admission import WIDTHS
        rpm=m.get('requests_per_minute')
        if (m['max_active_searches']!=3 or m['global_API_width'] not in WIDTHS
                or not m.get('candidate_policy') or rpm is not None and (type(rpm) is not int or rpm<1)):
            raise ValueError('invalid independent batch concurrency or request rate')
    if m['version']!=VERSION or not independent(m) and (m['max_active_searches']!=2 or m['global_API_width']!=1):
        raise ValueError('this release supports at most two searches and global API1 only')
    rows=m['members']
    policy=m.get('candidate_policy')
    if len(rows) not in ((1,2,3) if independent(m) else (1,2) if policy else (2,)) or len({r['run_id'] for r in rows})!=len(rows) or len({(r['group'],r['seed']) for r in rows})!=len(rows):
        raise ValueError('explicit independent group/seed identities required')
    if independent(m) and len({r['group'].split('-')[0] for r in rows})!=1:
        raise ValueError('one problem per independent batch')
    if len({r['run_dir'] for r in rows})!=len(rows) or not independent(m) and any(r['group']=='fjsp-u' and r['seed']==501 for r in rows):
        raise ValueError('distinct directories required; existing U501 is read-only')
    from experiments.triad.configuration import GROUPS
    if any(r['group'] not in GROUPS or type(r['seed']) is not int or not 0<=r['seed']<2**32
           or not policy and r['seed'] not in (501,502,503) or Path(r['run_dir']).name!=r['run_id']
           for r in rows):raise ValueError('declared triad group and allowed seed required')
    if not independent(m) and m['mode']=='real' and any(r['group']=='fjsp-u' and r['seed'] in (501,502) for r in rows):raise PermissionError('completed FJSP U501/U502 are read-only; never rerun or migrate')
    batch_local = independent(m) and Path(m['account_gate']) == path.parent / BATCH_GATE_DIR
    if m['mode']=='real' and not batch_local:
        expected=read(Path(__file__).resolve().parents[2]/'preparations/cluster-concurrency-20261114/phase1/Probe.pending.json')['account_gate']
        if m['account_gate']!=expected:raise ValueError('retain the original common account gate; no independent account locks')
    if m['total_request_cap']!=sum(r['request_cap'] for r in rows):raise ValueError('aggregate original cap differs')
    for row in rows:
        c=read(row['config'])
        if sha(row['config'])!=row['config_sha256'] or c['mode']!=m['mode'] or c['api_attempt_cap']!=row['request_cap'] or c['search_seed']!=row['seed'] or c.get('shared_manifest')!=str(path):raise ValueError('member configuration/mode/cap/seed binding changed')
        if c.get('candidate_policy')!=policy or policy and (not exploration(m) or row['group']=='fjsp-u' and not independent(m)):
            raise ValueError('shared candidate policy differs or needs the native exploration adapter')
        if policy:
            from experiments.triad.candidate_policy import validate
            validate(policy,c['evolution_request_cap'],real=m['mode']=='real')
            if c['resources'].get('request_queue_seconds',600)!=m['queue_wait_seconds']:
                raise ValueError('request queue wait differs from the drain calculation')
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
    if m['mode']=='real' and not independent(m) and (not m.get('account_exclusion') or m['account_exclusion'].get('valid_until',0)<=time.time()):
        raise PermissionError('fresh all-device exclusion required')
    identity={'protocol':'SHARED:'+sha(path),'batch':str(path),'version':VERSION}
    claim(path.parent/'Activation.json',{'state':'reserved','account_lease':str(lease),'identity':identity})
    claim(lease,identity)
    if not independent(m):claim(path.parent/'gate/ledger.json',{'version':VERSION,'manifest_sha256':sha(path),'next_ticket':0,'requests':{},'active':{},'jobs':{},'events':[],'peak':0,'last_sent_at':0})
    write(path.parent/'Activation.json',{'state':'active','account_lease':str(lease),'identity':identity})


class Admission:
    def __init__(self,b,deadline=None):
        self.b=b; self.path=Path(b['manifest']); self.m=load(self.path); self.folder=self.path.parent/'gate'
        self.member=b['run_id']; self.deadline=deadline
        self.row=next(r for r in self.m['members'] if r['run_id']==self.member)

    def verify(self):
        if sha(self.path)!=self.b['sha256']:raise ValueError('shared manifest identity changed')
        lease=Path(self.m['account_gate'])/'generation.lock'
        if not lease.is_file() or read(lease).get('protocol')!='SHARED:'+self.b['sha256']:
            if self.m.get('candidate_policy') and not independent(self.m):stop(self.folder,'original whole-account lease missing or changed')
            raise PermissionError('original batch ownership lock missing/different')
        if self.m['mode']=='real' and not independent(self.m) and self.m['account_exclusion']['valid_until']<time.time():
            stop(self.folder,'account exclusion expired');raise PermissionError('account exclusion expired; no renewal')

    @contextmanager
    def transaction(self):
        # Reuse the already tested exclusive writer; timeout never steals it.
        g=ProbeGate(self.folder,1,time.time()+10,0)
        refused=None
        with g.transaction():
            self.verify(); s=read(self.folder/'ledger.json')
            if s['manifest_sha256']!=self.b['sha256']:raise ValueError('shared ledger identity differs')
            before=digest(s)
            try:yield s
            except Exception as error:
                # A known read-only refusal (STOP, exhausted budget) has no
                # uncertain write to recover. Release THIS owned mutex normally
                # so an already-sent peer can still settle. Mutated/uncertain
                # transactions keep the original sticky-writer semantics.
                if digest(s)!=before:raise
                refused=error
            if digest(s)!=before:durable(self.folder/'ledger.json',s)
        if refused is not None:raise refused

    @staticmethod
    def event(s,event,**values):
        s['events'].append({'sequence':len(s['events']),'event':event,'at':time.time(),**values})

    def acquire(self,key):
        started=time.monotonic(); uid=digest({'member':self.member,'key':key})
        # One frozen U transport adapter survives the whole search. Queue time
        # is bounded PER REQUEST, not 360 seconds after process construction.
        self.wait_deadline=self.deadline if self.deadline is not None else time.time()+self.m['queue_wait_seconds']
        with self.transaction() as s:
            if (self.folder/'STOP.json').exists():raise RuntimeError('shared STOP: no new requests')
            if self.member not in s['jobs']:raise RuntimeError('request without active admitted search')
            if uid in s['requests']:raise RuntimeError('attempt already reserved; never replay or refund')
            if sum(r['member']==self.member for r in s['requests'].values())>=self.row['request_cap'] or len(s['requests'])>=self.m['total_request_cap']:
                raise RuntimeError('original member/aggregate request cap exhausted')
            width,phase_cap=self.phase(s)
            if phase_cap is not None and len(s['requests'])>=phase_cap:raise PermissionError('finite API2 phase cap reached; no extra reservations or automatic full search')
            s['requests'][uid]={'member':self.member,'key':key,'ticket':s['next_ticket'],'state':'waiting','reserved_at':time.time()}
            s['next_ticket']+=1; self.event(s,'waiting',uid=uid,member=self.member)
        while True:
            if time.time()>=self.wait_deadline:
                if not exploration(self.m):stop(self.folder,'bounded queue wait ended; reservations retained, no replay')
                raise TimeoutError('request admission wait exceeded; no refund')
            with self.transaction() as s:
                if (self.folder/'STOP.json').exists():raise RuntimeError('shared STOP while waiting; reservation retained')
                waiting=[(v['ticket'],k) for k,v in s['requests'].items() if v['state']=='waiting']
                first=min(waiting)[1] if waiting else None
                width,_=self.phase(s)
                if (len(s['active'])<width and self.member not in s['active'].values() and first==uid
                    and time.time()>=s.get('rate_resume_at',0)):
                    s['active'][uid]=self.member; s['peak']=max(s['peak'],len(s['active']))
                    s['requests'][uid].update(state='admitted',wait_seconds=time.monotonic()-started)
                    self.event(s,'admitted',uid=uid,member=self.member);return uid
            time.sleep(.1)

    def phase(self,s):
        if exploration(self.m):return self.m['global_API_width'],None
        path=self.path.parent/'API2.finite.json'
        if not path.exists():return 1,None
        r=read(path)
        if r['manifest_sha256']!=self.b['sha256'] or r['adapter_sha256']!=sha(__file__):raise ValueError('API2 finite authorization binding changed')
        s=read(self.folder/'ledger.json') if s is None else s
        if s.get('API2_finite_sha256')!=sha(path):raise ValueError('original API2 finite authorization bytes changed or were never durably admitted')
        if self.m['mode']=='real' and (r.get('before_reservations')!=2 or r.get('reservation_stop_at')!=4 or r.get('additional_requests')!=2 or r.get('additional_solves_upper')!=84):raise PermissionError('only the explicit2 additional requests/84 solves phase is implemented')
        decision=self.path.parent/'API2.decision.json'
        if decision.exists():
            v=read(decision)
            if s.get('API2_decision_sha256')!=sha(decision):raise ValueError('original API2 decision bytes changed')
            if v['finite_sha256']!=sha(path) or v['width'] not in (1,2):raise ValueError('API2 decision binding changed')
            if v['width']==2 and v['acceptance_sha256']!=sha(self.path.parent/'API2.Acceptance.json'):raise ValueError('actual API2 acceptance required')
            return v['width'],None
        return 2,r['reservation_stop_at']

    def send_turn(self,uid):
        """Serialize send starts without blocking ledger settlement or peer STOP.

        The next holder waits a local monotonic interval AFTER the previous
        physical-send callback releases this file. No cross-node clock sync is
        assumed. Unknown owners are sticky; no TTL stealing.
        """
        path=self.folder/'send-turn.lock'
        while time.time()<self.wait_deadline:
            if (self.folder/'STOP.json').exists():raise RuntimeError('STOP before send turn; no new wire')
            try:claim(path,{'uid':uid,'member':self.member});break
            except FileExistsError:time.sleep(.05)
        else:raise TimeoutError('bounded send-turn wait ended; unknown owner retained')
        time.sleep(self.m['min_request_interval_seconds'])
        self.verify()
        if (self.folder/'STOP.json').exists():raise RuntimeError('STOP while pacing; owned turn retained')
        return path

    def release_send_turn(self,path,uid):
        if read(path)!=dict(uid=uid,member=self.member):raise RuntimeError('send turn ownership changed')
        path.unlink()

    def sent(self,uid):
        with self.transaction() as s:
            r=s['requests'][uid]
            if s['active'].get(uid)!=self.member or r['state']!='admitted':raise RuntimeError('send without owned permit')
            # The V5 callback arrives AFTER the physical send. A peer STOP may
            # have appeared meanwhile; account for this admitted send and drain
            # its response rather than aborting a known in-flight request.
            r.update(state='sent',sent_at=time.time(),pacing_seconds=self.m['min_request_interval_seconds']);s['last_sent_at']=r['sent_at'];self.event(s,'sent',uid=uid,member=self.member)

    def settled(self,uid,value,wire_seconds):
        with self.transaction() as s:
            r=s['requests'][uid]
            if s['active'].get(uid)!=self.member or r['state']!='sent':raise RuntimeError('response without known owned send')
            r.update(state='completed',finished_at=time.time(),usage=value.get('usage'),wire_seconds=wire_seconds,wire_timing=(value.get('metadata') or {}).get('wire_timing'))
            del s['active'][uid];self.event(s,'settled',uid=uid,member=self.member)

    def failed(self,uid,error):
        if exploration(self.m):
            return self.known_failure(uid,error)
        # No classification releases a failed permit in this conservative first release.
        stop(self.folder,'first transport/admission failure; shared sends stopped; inspect retained reservation')
        with self.transaction() as s:
            s['requests'][uid].update(state='failed_or_unknown',error_type=type(error).__name__,send_state=(getattr(error,'metadata',{}) or {}).get('send_status','unknown'),finished_at=time.time())
            self.event(s,'failed_or_unknown',uid=uid,member=self.member)

    def known_failure(self,uid,error):
        """Only terminal, owned attempts are settled. Charges and failed evidence remain."""
        from fjsp_usage.research_real.attempt_budget import failure_policy
        meta=getattr(error,'metadata',{}) or {}
        _,category,permanent=failure_policy(str(error),meta,type(error).__name__)
        account_error=bool(meta.get('caller_hard_stop') or permanent or meta.get('http_status')==429 or meta.get('upstream_http_status')==429 or meta.get('failure_class') in ('protocol_incompatible','permanent'))
        not_sent=meta.get('send_status') in ('not_sent','not_started')
        http_terminal=type(meta.get('http_status')) is int and 400<=meta['http_status']<=599 and meta.get('send_status')=='confirmed'
        policy=self.m.get('candidate_policy')
        if policy:
            from experiments.triad.candidate_policy import failure
            _,category,account_error=failure(policy,str(error),meta,type(error).__name__)
            http_terminal=http_terminal and meta.get('failure_stage')=='http_receive'
        usage=getattr(error,'usage',None)
        usage_known=isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('input_tokens','output_tokens'))
        # A terminal HTTP failure keeps its charge even without provider usage.
        # The candidate policy may settle its permit without replaying the send.
        known=bool(meta.get('dispatch_children_settled') is True and
                   (not_sent or http_terminal and (usage_known or policy)))
        if account_error or not known:stop(self.folder,'account-level failure' if account_error else 'unknown send/worker/usage; reservation retained')
        turn=self.folder/'send-turn.lock';owned_turn=False
        with self.transaction() as s:
            r=s['requests'].get(uid)
            if r is None:
                # The local journal already charged this slot before admission.
                if not known or not not_sent or self.member not in s['jobs'] or len(s['requests'])>=self.m['total_request_cap'] or sum(x['member']==self.member for x in s['requests'].values())>=self.row['request_cap']:
                    stop(self.folder,'unmatched charged attempt retained')
                    raise RuntimeError('unmatched charged attempt; retain original journal and STOP')
                r={'member':self.member,'key':meta['request_key'],'ticket':s['next_ticket'],'reserved_at':time.time(),'state':'waiting'}
                s['next_ticket']+=1;s['requests'][uid]=r
            if r['member']!=self.member or r['state'] not in ('waiting','admitted','sent') or s['active'].get(uid) not in (None,self.member):
                stop(self.folder,'request ownership/state mismatch; no cleanup')
                raise RuntimeError('failure does not own an unsettled attempt')
            if r['state']=='waiting' and uid in s['active']:
                stop(self.folder,'waiting request unexpectedly owns a permit; retain evidence')
                raise RuntimeError('waiting state conflicts with permit ownership')
            # A proven unsent waiter never acquired the send turn. A peer can
            # legitimately hold it while this waiter reaches its own deadline.
            if not (policy and known and not_sent and r['state']=='waiting'):
                try:owner=read(turn)
                except FileNotFoundError:owner=None
                if owner is not None:
                    owned_turn=owner=={'uid':uid,'member':self.member}
                    if not owned_turn:stop(self.folder,'foreign/unknown send turn retained')
            if not_sent and r['state']=='sent':
                known=False;stop(self.folder,'wire/ledger send evidence differs; retain permit')
            if http_terminal and (r['state']!='sent' or s['active'].get(uid)!=self.member):
                known=False;stop(self.folder,'HTTP metadata without owned sent permit; retain evidence')
            if policy and known and http_terminal and meta['http_status']==429:
                s['rate_resume_at']=max(s.get('rate_resume_at',0),time.time()+policy['rate_limit_backoff_seconds'])
            r.update(state='reconciled_failed' if known else 'failed_or_unknown',error_type=type(error).__name__,
                send_state=meta.get('send_status','unknown'),finished_at=time.time(),usage=getattr(error,'usage',None),
                failure_category=category,account_stop=account_error,metadata={k:meta.get(k) for k in
                ('http_status','upstream_http_status','failure_stage','send_status','caller_hard_stop','dispatch_children_settled')})
            if known and s['active'].get(uid)==self.member:del s['active'][uid]
            self.event(s,r['state'],uid=uid,member=self.member)
        if known and owned_turn:
            try:self.release_send_turn(turn,uid)
            except BaseException:
                stop(self.folder,'owned send turn changed during settlement; no cleanup')
                raise

    @contextmanager
    def session(self,directory):
        verify_attachment(directory,self.b)
        d=Path(directory); token=str(os.getpid())+'-'+str(time.time_ns()); registered=False
        if self.m['mode']=='real':
            job=os.environ.get('SLURM_JOB_ID','');node=os.environ.get('SLURM_JOB_NODELIST') or os.environ.get('SLURM_NODELIST')
            if not job.isdigit() or not node:raise PermissionError('shared real searches execute only in an explicit Slurm compute allocation')
            certificate=self.path.parent/'Acceptance.json'
            if certificate.exists() and not exploration(self.m):
                role=next(i for i,r in enumerate(self.m['members']) if r['run_id']==self.member)
                if node!=read(certificate)['validated_nodes'][role]:raise PermissionError('new topology not accepted; do not migrate or bypass the validated node binding')
        if independent(self.m):
            self.verify()
            if os.environ.get('SLURM_JOB_ID'):
                job=os.environ['SLURM_JOB_ID']
                allocation=wait_file(self.path.parent/'Current_allocation.json',time.time()+self.m['queue_wait_seconds'],self.path.parent)
                end=time.monotonic()+self.m['queue_wait_seconds']
                while allocation.get('state')=='reserved' and time.monotonic()<end:
                    time.sleep(.05)
                    allocation=read(self.path.parent/'Current_allocation.json')
                if (allocation.get('manifest_sha256')!=self.b['sha256']
                        or allocation.get('jobs',{}).get(self.member)!=job):
                    raise PermissionError('original Slurm submission receipt does not match')
                if self.m['mode']=='real':allocation_check(read(self.row['config']))
            yield
            return
        try:
            with self.transaction() as s:
                if (self.folder/'STOP.json').exists():raise RuntimeError('shared STOP retained; no automatic recovery')
                if self.member in s['jobs'] or len(s['jobs'])>=2:raise RuntimeError('active/unknown search lease retained')
                s['jobs'][self.member]={'token':token,'pid':os.getpid(),'host':__import__('socket').gethostname()}
                self.event(s,'search_started',member=self.member);registered=True
            if self.m.get('require_initial_preflight'):
                role=next(i for i,r in enumerate(self.m['members']) if r['run_id']==self.member)
                preflight=self.path.parent/'preflight';preflight.mkdir(exist_ok=True)
                if exploration(self.m):
                    try:self.startup(directory)
                    except BaseException:
                        stop(self.folder,'allocation selfcheck failed; no new sends')
                        raise
                elif not (preflight/f'fs-pass-{role}.json').exists():
                    filesystem_check(preflight,role,time.time()+self.m['queue_wait_seconds'])
            yield
        finally:
            if registered:
                cp=read(d/'checkpoint.json');safe=cp['phase'] in (('prepared','completed','paused','initialization_incomplete','expired') if exploration(self.m) else ('completed','paused','initialization_incomplete','expired')) and not (d/'Stop.json').exists()
                with self.transaction() as s:
                    safe=safe and not any(v==self.member for v in s['active'].values()) and not any(v['member']==self.member and v['state'] not in ('completed','reconciled_failed') for v in s['requests'].values())
                    if safe and s['jobs'].get(self.member,{}).get('token')==token:
                        del s['jobs'][self.member];self.event(s,'search_settled',member=self.member,phase=cp['phase'])
                    else:stop(self.folder,'search ended without certified settlement; keep job/request reservations')

    def startup(self,directory):
        """Fresh allocation rendezvous. No credential value, model or solver is read."""
        self.verify()
        c=read(self.row['config']);job=os.environ.get('SLURM_JOB_ID','')
        if self.m['mode']=='real':
            allocation_check(c)
            private=Path(c['account_gate'])/'generation.lock'
            if private.exists():
                owner=read(private);state=read(Path(directory)/'checkpoint.json')
                if owner.get('pid')!=os.getpid() or owner.get('run_id')!=self.member or owner.get('protocol')!=state['identity']:
                    raise PermissionError('foreign/unknown member writer retained before credential read')
        end=time.time()+self.m['queue_wait_seconds'];allocation=None
        while time.time()<end:
            self.verify()
            if (self.folder/'STOP.json').exists():raise PermissionError('STOP before startup; no credential read')
            current=self.path.parent/'Current_allocation.json'
            if current.exists():
                allocation=read(current)
                if allocation.get('state')=='submitted' and allocation.get('jobs',{}).get(self.member)==job:break
            time.sleep(.05)
        else:raise TimeoutError('bounded allocation receipt wait; no secret read')
        jobs=allocation.get('jobs',{})
        if allocation.get('manifest_sha256')!=self.b['sha256'] or len(jobs) not in (1,2) or any(not str(j).isdigit() for j in jobs.values()) or not set(jobs).issubset({r['run_id'] for r in self.m['members']}) or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for ch in allocation['identity']):
            raise ValueError('fresh allocation identity differs; no reused preflight')
        ledger=read(self.folder/'ledger.json')
        if self.member in ledger['active'].values() or any(r['state'] not in ('waiting','admitted','sent','completed','reconciled_failed') for r in ledger['requests'].values()):
            raise PermissionError('unknown/retained request before credential read')
        if set(ledger['jobs'])-set(jobs):raise PermissionError('active peer outside this fresh allocation')
        role=next(i for i,r in enumerate(self.m['members']) if r['run_id']==self.member)
        folder=self.path.parent/'preflight'/allocation['identity'];folder.mkdir(parents=True,exist_ok=True)
        independent=self.m.get('candidate_policy') is not None
        paired=not independent and len(jobs)==2
        probe=folder/f'member-{role}' if independent else folder
        claim(probe/f'participant-{role}.json',{'job_id':job,'pid':os.getpid(),'host':__import__('socket').gethostname(),'member':self.member})
        if paired:
            filesystem_check(probe,role,end)
        else:
            # Each candidate job validates its own allocation even when the
            # scheduler has not started its peer. Cross-node checks are a site test.
            context=multiprocessing.get_context('fork')
            child=context.Process(target=local_filesystem_probe,args=(probe,1-role,end));child.start()
            try:
                filesystem_check(probe,role,end);child.join(max(0,end-time.time()))
                if child.is_alive() or child.exitcode!=0:raise RuntimeError('local filesystem probe incomplete')
            finally:
                if child.is_alive():child.terminate();child.join()
        claim(folder/f'startup-pass-{role}.json',{'job_id':job,'pid':os.getpid(),'member':self.member,'API_requests':0,'scope':'two_jobs' if paired else 'one_job_local_probe'})
        self.verify()


class GuardedTransport:
    """Wrap the actual V5 dispatch, releasing its permit before CPU evaluation."""
    def __init__(self,inner,admission):
        self.inner=inner;self.admission=admission;self.config=inner.config
        self.identity=digest({'transport':inner.identity,'shared':admission.b,'version':VERSION})
    def __getattr__(self,name):return getattr(self.inner,name)
    def preflight(self,prompt):return self.inner.preflight(prompt)
    def dispatch(self,key,prompt,*,kind,on_sent):
        if not self.admission.m.get('candidate_policy'):
            verify_attachment(self.admission.row['run_dir'],self.admission.b)
        light=exploration(self.admission.m)
        uid=digest({'member':self.admission.member,'key':key})
        try:uid=self.admission.acquire(key)
        except BaseException as error:
            error.metadata={**(getattr(error,'metadata',{}) or {}),'send_status':'not_sent','failure_stage':'shared_admission'}
            if light:
                error.metadata.update(dispatch_children_settled=True,request_key=key,
                    shared_stop=(self.admission.folder/'STOP.json').exists())
                self.admission.failed(uid,error)
            raise
        inner_started=False
        children={p.pid for p in multiprocessing.active_children()} if light else set()
        try:
            turn=self.admission.send_turn(uid)
            self.admission.verify()
            if (self.admission.folder/'STOP.json').exists():raise RuntimeError('shared STOP before wire dispatch')
            clock=Path(self.admission.row['run_dir'])/'Run_clock.json'
            c=read(self.admission.row['config'])
            from .configuration import request_timeout
            reserve=request_timeout(c)+c['instance_timeout_seconds']*c['instance_count']+5
            if clock.exists() and time.time()+reserve>read(clock)['deadline']:
                raise TimeoutError('original calendar window cannot cover dispatch and evaluation after waiting')
            def sent():
                self.admission.sent(uid);on_sent()
                self.admission.release_send_turn(turn,uid)
            inner_started=True
            wire_started=time.monotonic()
            value=self.inner.dispatch(key,prompt,kind=kind,on_sent=sent)
            self.admission.settled(uid,value,time.monotonic()-wire_started);return value
        except BaseException as error:
            if not inner_started:error.metadata={**(getattr(error,'metadata',{}) or {}),'send_status':'not_sent','failure_stage':'shared_admission'}
            if light:
                error.metadata={**(getattr(error,'metadata',{}) or {}),'dispatch_children_settled':not any(p.pid not in children for p in multiprocessing.active_children()),'request_key':key,
                    'shared_stop':(self.admission.folder/'STOP.json').exists()}
            self.admission.failed(uid,error);raise


def adapter(b):
    from experiments.triad.runtime import Adapter
    from experiments.triad import candidate_policy
    manifest=load(b['manifest']);policy=manifest.get('candidate_policy')
    class AdmittedAdapter(Adapter):
        pause_on_transport_streak=exploration(manifest)
        validate_once_per_segment=bool(policy)
        transport_streak_limit=policy['failure_streak_limit'] if policy else 3
        def request_candidate(self,journal,key,prompt,kind,record):
            if policy:return journal.request_candidate(key,prompt,kind,record)
            return journal.request(key,prompt,kind=kind)
        def stop_after_task(self,s,p):
            if not policy:return False
            if s.get('successful_evolution_responses',0)==p['config']['evolution_request_cap']:
                s.update(phase='completed',pause_reason=None)
            elif s['tasks'][next(reversed(s['tasks']))].get('attempt_stage_exhausted') and s['eoh']['stage']=='evolution':
                s.update(phase='paused',pause_reason=candidate_policy.BUDGET_PAUSE)
            elif self.transport_streak_limit and s.get('transport_failure_streak',0)>=self.transport_streak_limit:
                s.update(phase='paused',pause_reason=candidate_policy.STREAK_PAUSE)
            else:return False
            return True
        def check_run(self,d):
            p=super().check_run(d);verify_attachment(d,b);return p
        def transport(self,p):
            inner=super().transport(p);admission=Admission(b)
            if independent(manifest):
                from .batch_admission import Transport
                return Transport(inner,admission,policy)
            return GuardedTransport(inner,admission)
        def task_context(self,d,s,p,task,index):
            if (Path(b['manifest']).parent/'gate/STOP.json').exists():
                s.update(phase='paused',pause_reason='shared STOP before candidate planning/reservation; manual audited recovery required');return None,[]
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
