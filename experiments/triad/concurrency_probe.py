#!/usr/bin/env python3
"""Two independent engineering jobs, bounded V5 requests; never evaluate programs."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core.execution_contract import send_state
from heuristic_design.llm.legacy import ClientConfig,WireRecorder
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport,StopAwareJournal


def claim(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())


def stop(folder,reason):
    try:claim(Path(folder)/'STOP.json',{'reason':reason,'at':time.time(),'automatic_retry':False})
    except FileExistsError:pass


def wait_file(path,deadline,folder):
    while True:
        if (Path(folder)/'STOP.json').exists() or time.time()>deadline:raise RuntimeError('peer/phase not ready; bounded stop, no request replay')
        if Path(path).exists():
            try:return read(path)
            except json.JSONDecodeError:pass # another job is fsyncing its exclusive claim
        time.sleep(.1)


class Gate:
    """Sticky on uncertainty. O_EXCL and fixed-file visibility are probed first."""
    def __init__(self,folder,width,deadline,interval):self.folder=Path(folder);self.width=width;self.deadline=deadline;self.interval=interval;self.folder.mkdir(parents=True,exist_ok=True)
    @contextmanager
    def transaction(self):
        path=self.folder/'metrics.lock';token=uuid.uuid4().hex
        while True:
            try:claim(path,{'owner':token});break
            except FileExistsError:
                if time.time()>self.deadline:stop(self.folder,'unknown/stuck metrics owner; never TTL-unlock');raise TimeoutError('metrics writer is unknown')
                time.sleep(.05)
        normal=False
        try:yield;normal=True
        finally:
            if normal and read(path)['owner']==token:path.unlink()
    def event(self,key,state,**extra):
        with self.transaction():
            path=self.folder/'metrics.json';m=read(path) if path.exists() else {'active':{},'peak':0,'events':[],'last_dispatch':0}
            if state=='sent':m['active'][key]=extra;m['last_dispatch']=time.time()
            if state=='settled':m['active'].pop(key,None)
            m['peak']=max(m['peak'],len(m['active']));m['events'].append({'sequence':len(m['events'])+1,'key':key,'state':state,'at_unix':time.time(),**extra});write(path,m)
            if m['peak']>self.width:stop(self.folder,'observed global width exceeded');raise RuntimeError('global in-flight bound exceeded')
    def acquire(self,key):
        while time.time()<self.deadline:
            if (self.folder/'STOP.json').exists():raise RuntimeError('global STOP; no new allocation')
            for i in range(self.width):
                path=self.folder/f'slot-{i}.json'
                try:claim(path,{'key':key,'state':'reserved','at':time.time()})
                except FileExistsError:continue
                # One atomic metadata transaction serializes global request pacing.
                with self.transaction():
                    last=read(self.folder/'metrics.json').get('last_admission',0) if (self.folder/'metrics.json').exists() else 0
                    delay=last+self.interval-time.time()
                    if delay>0:time.sleep(delay)
                    if (self.folder/'STOP.json').exists():raise RuntimeError('global stop during admission')
                    m=read(self.folder/'metrics.json') if (self.folder/'metrics.json').exists() else {'active':{},'peak':0,'events':[],'last_dispatch':0}
                    m['last_admission']=time.time();write(self.folder/'metrics.json',m)
                self.event(key,'admitted',slot=i);return path
            time.sleep(.05)
        stop(self.folder,'bounded admission deadline');raise TimeoutError('no gate permit; no stale lock removal')


class GuardedWire:
    def __init__(self,wire,gate,job):
        self.wire,self.gate,self.job=wire,gate,job;self.config=wire.config;self.directory=wire.directory;self.identity=digest({'V5':wire.identity,'gate':'engineering-shared-v1','width':gate.width});self.redact=wire.redact
    def preflight(self,prompt):return self.wire.preflight(prompt)
    def dispatch(self,key,prompt,*,kind,on_sent):
        slot=self.gate.acquire(key)
        def sent():
            write(slot,{'key':key,'state':'sent','at':time.time(),'job':self.job});self.gate.event(key,'sent',job=self.job);on_sent()
        try:value=self.wire.dispatch(key,prompt,kind=kind,on_sent=sent)
        except BaseException as e:
            # Even known failures halt allocation; uncertain sends keep their slot forever.
            m=getattr(e,'metadata',{}) or {};stop(self.gate.folder,'first HTTP/auth/protocol/transport/unknown error')
            state=send_state({'metadata':m})
            self.gate.event(key,'failed_or_unknown',job=self.job,send_state=state,http_status=m.get('http_status'))
            raise
        self.gate.event(key,'settled',job=self.job,usage=value.get('usage'),http_status=(value.get('metadata') or {}).get('http_status'))
        if read(slot)['key']!=key:raise RuntimeError('shared gate ownership changed')
        slot.unlink();return value


def filesystem_check(folder,role,deadline):
    """Both actual Slurm jobs observe a live exclusive claim and sticky unknown."""
    folder=Path(folder);peer=1-role;host=socket.gethostname()
    claim(folder/f'ready-{role}.json',{'host':host,'job_id':os.environ.get('SLURM_JOB_ID'),'role':role})
    other=wait_file(folder/f'ready-{peer}.json',deadline,folder);path=folder/'fs-exclusive.json'
    if role==0:
        claim(path,{'owner':0,'nonce':uuid.uuid4().hex});claim(folder/'fs-held.json',read(path));wait_file(folder/'fs-observed.json',deadline,folder)
        if read(path)!=read(folder/'fs-held.json'):raise RuntimeError('shared O_EXCL owner changed')
        path.unlink();claim(folder/'fs-released.json',{'known_settlement':True})
    else:
        held=wait_file(folder/'fs-held.json',deadline,folder)
        try:claim(path,{'owner':1})
        except FileExistsError:pass
        else:raise RuntimeError('two jobs acquired the same exclusive file')
        if read(path)!=held:raise RuntimeError('shared filesystem visibility mismatch')
        claim(folder/'fs-observed.json',{'live_owner_seen':True});wait_file(folder/'fs-released.json',deadline,folder)
    if role==0:claim(folder/'fs-unknown.lock',{'state':'UNKNOWN_FIXTURE_KEEP','not_an_API_request':True})
    else:
        wait_file(folder/'fs-unknown.lock',deadline,folder)
        try:claim(folder/'fs-unknown.lock',{'state':'wrong'})
        except FileExistsError:pass
        else:raise RuntimeError('unknown claim was replayed')
    claim(folder/f'fs-pass-{role}.json',{'role':role,'host':host,'peer_host':other['host'],'passed':True,'unknown_fixture_retained':True})
    wait_file(folder/f'fs-pass-{peer}.json',deadline,folder)


def prepare(phase,output):
    """Static prompt generation only, no H/U execution or model request."""
    from experiments.triad import runtime,configuration
    source=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['client_binding'];folder=Path(output)
    if folder.exists():raise FileExistsError('preserve prior probe identity and reservations')
    if phase==2:raise PermissionError('phase2 preparation requires a passed phase1 receipt; use the staged controller')
    folder.mkdir(parents=True)
    c=configuration.load(ROOT/'experiments/triad/recommended.draft/fjsp-eoh.json');a=runtime.Adapter();a.p={'run_kind':'eoh'};eoh=a.build_prompt(c,{'operator':'I1'},[],[])
    from heuristic_design.core.evolution_v1 import contract_language
    t=read(ROOT/'preparations/triad/fjsp/U_frozen_template.json')['settings'];members=[r.get('candidate',r) for r in read(ROOT/'preparations/triad/fjsp/H_frozen.json')['members']]
    usage=contract_language(t).build_prompt('fjsp',{'operator':'INIT'},[],members,window=t['window'])
    prompts=[]
    for role,text in enumerate((eoh,usage)):
        path=folder/f'role-{role}-representative.txt';path.write_text(text);prompts.append({'role':role,'path':path.name,'sha256':sha(path),'bytes':len(text.encode()),'kind':'h' if role==0 else 'U','source':'actual EoH I1 / frozen U INIT prompt builder; training inputs only'})
    spec={'version':'cluster-two-job-API-probe-v1','phase':1,'approved':False,'jobs':2,'requests_per_job':2,'physical_send_cap':4,'global_API_width':1,'per_attempt_cap':1,'min_request_interval_seconds':1,'provider':source['provider'],'client_binding':source,'prompts':prompts,'credential_file':'/public2/home/qiuqian/.config/hdl/leafapi.key','account_gate':'/public2/home/qiuqian/hdl-account-gates/leafapi-gpt61sol-serial-v1','wall_seconds':1800,'peer_wait_seconds':300,'request_timeout_seconds':source['provider']['total_timeout'],'max_output_tokens':source['provider']['max_output_tokens'],'resources':{'cpus_per_job':1,'memory_mib_per_job':1024,'partition':'128C_02','account':'wz','qos':'normal'},'solver_calls':0,'fees':'unknown, no currency hard cap','limits':{'RPM':None,'TPM':None,'provider_concurrency':None},'rate_limit_headers':'V5 exposes only its existing allowlist; missing RPM/TPM headers remain unknown; no additional query','second_phase':'optional separate user approval, 4 additional sends maximum; never automatic'}
    write(folder/'Probe.pending.json',spec);return spec


def worker(folder,role,approve_sends):
    folder=Path(folder);p=read(folder/'Probe.json');auth=read(folder/'Approval.json');job=os.environ.get('SLURM_JOB_ID')
    if not job or role not in (0,1) or approve_sends!=4 or auth.get('approved_physical_sends')!=4 or auth.get('confirm_all_devices_exclusive') is not True or auth.get('probe_sha256')!=sha(folder/'Probe.json'):raise PermissionError('manual four-send engineering approval and independent Slurm identity required')
    if p['phase'] not in (1,2) or p['global_API_width']!=p['phase'] or p['requests_per_job']!=2 or p['physical_send_cap']!=4 or p['per_attempt_cap']!=1:raise ValueError('fixed 4+4 maximum; no expansion')
    binding=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['client_binding']
    if p['client_binding']!=binding or p['provider']!=binding['provider']:raise ValueError('same current model/provider/V5 required')
    if p['phase']==2:
        first=read(folder.parent/'phase1/PASS.json')
        if first.get('passed') is not True or p.get('phase1_pass_sha256')!=sha(folder.parent/'phase1/PASS.json'):raise PermissionError('phase1 must pass first; no automatic API2')
    deadline=min(time.time()+p['wall_seconds']-60,auth['exclusive_until']);local=folder/f'job-{role}';local.mkdir(exist_ok=True)
    claim(local/'worker.lock',{'job_id':job,'role':role,'no_reentry':True});write(local/'status.json',{'phase':'preflight','job':job,'host':socket.gethostname()})
    gate=Gate(folder/'gate',p['global_API_width'],deadline,p['min_request_interval_seconds'])
    try:
        lease=Path(p['account_gate'])/'generation.lock'
        if read(lease)['protocol']!='PROBE:'+sha(folder/'Probe.json'):raise ValueError('engineering account lease ownership differs')
        filesystem_check(folder,role,min(deadline,time.time()+p['peer_wait_seconds']))
        for name,h in p['client_binding']['files'].items():
            if sha(ROOT/name)!=h:raise ValueError('admitted V5 source differs')
        prompt=folder/p['prompts'][role]['path']
        if sha(prompt)!=p['prompts'][role]['sha256']:raise ValueError('representative prompt differs')
        from experiments.triad.entry import key
        key({'credential_file':p['credential_file'],'provider':p['provider']})
        config=ClientConfig({'config':{'provider':p['provider'],'api_mode':'real','real_requests_authorized':True,'api_attempt_cap':2,'per_candidate_attempt_cap':1},'budgets':{'logical_generation':2}})
        def verify():
            for name,h in {**p['client_binding']['files'],**p.get('engineering_sources',{})}.items():
                if sha(ROOT/name)!=h:raise ValueError('frozen V5/engineering source changed; no dispatch')
        wire=WireRecorder(StrictNonstreamTransport(config),local/'wire',verify=verify)
        guarded=GuardedWire(wire,gate,job);journal=StopAwareJournal(local/'API_attempts.json',config=config,context=sha(folder/'Probe.json'),phase=f'engineering-phase{p["phase"]}-job{role}',transport=guarded)
        for i in range(2):
            if read(lease)['protocol']!='PROBE:'+sha(folder/'Probe.json'):raise ValueError('engineering account lease changed; no new dispatch')
            if (gate.folder/'STOP.json').exists() or time.time()+p['request_timeout_seconds']>deadline:raise RuntimeError('stop/deadline before next request reservation')
            if p['phase']==2:
                claim(folder/f'round-{i}-ready-{role}.json',{'job':job});wait_file(folder/f'round-{i}-ready-{1-role}.json',deadline,folder)
            reply=journal.request(f'role{role}-request{i}',prompt.read_text(),kind=p['prompts'][role]['kind'])
            if reply['status']!='completed':stop(gate.folder,'first failed/unknown response');raise RuntimeError('engineering request failed; no retries or candidate evaluation')
        write(local/'status.json',{'phase':'completed','job':job,'host':socket.gethostname(),'requests':2,'solver_calls':0})
    except BaseException as e:
        stop(gate.folder,type(e).__name__);write(local/'status.json',{'phase':'stopped','job':job,'error_type':type(e).__name__,'no_retry':True});raise
    return collect(folder)


def collect(folder):
    folder=Path(folder);spec=read(folder/'Probe.json');states=[];attempts=[]
    for role in (0,1):
        d=folder/f'job-{role}';states.append(read(d/'status.json') if (d/'status.json').exists() else {'phase':'not_started'})
        if (d/'API_attempts.json').exists():attempts += list(read(d/'API_attempts.json')['api_attempts'].values())
    metrics=read(folder/'gate/metrics.json') if (folder/'gate/metrics.json').exists() else {'peak':0,'active':{},'events':[]}
    metadata=[a.get('reply',{}).get('metadata',a.get('metadata',{})) for a in attempts]
    confirmed=sum(a.get('send_confirmed',False) for a in attempts);unknown=sum(a['status'] not in ('completed','failed') or send_state({'metadata':m})=='unknown' and not a.get('send_confirmed',False) for a,m in zip(attempts,metadata));usage=[a.get('usage') for a in attempts]
    receipts=[read(folder/'submissions'/f'role-{r}.json') if (folder/'submissions'/f'role-{r}.json').exists() else {} for r in (0,1)]
    jobs_verified=all(v.get('state')=='submitted' and v.get('job_id')==s.get('job') and str(s.get('job','')).isdigit() for v,s in zip(receipts,states))
    passed=jobs_verified and all(s['phase']=='completed' for s in states) and len(attempts)==4 and confirmed==4 and not unknown and not metrics['active'] and not (folder/'gate/STOP.json').exists() and metrics['peak']==spec['global_API_width']
    hosts=[read(folder/f'ready-{i}.json')['host'] if (folder/f'ready-{i}.json').exists() else None for i in (0,1)]
    result={'passed':passed,'phase':spec['phase'],'states':states,'independent_Slurm_receipts_verified':jobs_verified,'reserved_attempts':len(attempts),'confirmed_sends':confirmed,'unknown_attempts':unknown,'retained_active_after_error':len(metrics['active']),'physical_send_cap':4,'automatic_retries':0,'global_inflight_peak':metrics['peak'],'host_scope':'cross_node' if all(hosts) and hosts[0]!=hosts[1] else 'same_node_or_unknown','hosts':hosts,'known_usage_subtotal':{k:sum((u or {}).get(k,0) for u in usage) for k in ('input_tokens','output_tokens')},'unknown_usage_attempts':sum(u is None for u in usage),'HTTP_statuses':[m.get('http_status') for m in metadata],'request_receipts':[{'attempt_id':a['id'],'reserved_at':a.get('started_at'),'finished_at':a.get('finished_at'),'wire_timing':m.get('wire_timing'),'send_confirmed':a.get('send_confirmed',False),'HTTP_status':m.get('http_status'),'usage':a.get('usage')} for a,m in zip(attempts,metadata)],'actual_cost':None,'official_limits_still_unknown':True,'rate_limit_headers_available':False,'solver_calls':0,'research_population_updates':0,'interpretation':'only this specified load and topology; not an official concurrency/RPM/TPM limit'}
    try:claim(folder/'collect.lock',{'pid':os.getpid()})
    except FileExistsError:return {**result,'collection_busy':True}
    write(folder/'Result.json',result)
    if passed:
        write(folder/'PASS.json',result)
        lease=Path(spec['account_gate'])/'generation.lock'
        if lease.exists() and read(lease)['protocol']=='PROBE:'+sha(folder/'Probe.json'):lease.unlink()
    (folder/'collect.lock').unlink()
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['prepare','worker','collect']);ap.add_argument('--directory',type=Path,required=True);ap.add_argument('--role',type=int);ap.add_argument('--phase',type=int,default=1);ap.add_argument('--approve-sends',type=int);a=ap.parse_args()
    result=prepare(a.phase,a.directory) if a.action=='prepare' else worker(a.directory,a.role,a.approve_sends) if a.action=='worker' else collect(a.directory)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False}),file=sys.stderr);raise SystemExit(2)
