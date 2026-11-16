#!/usr/bin/env python3
"""Specific audited R9 recovery. No search, HTTP, retry or solver implementation."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core import execution
from heuristic_design.llm.legacy import WireRecorder,DeadlineTransport
from heuristic_design.llm.strict_nonstream import StopAwareJournal
from experiments.triad import runtime,configuration,shared_admission as shared,parallel,native_continuation as previous
from experiments.triad.concurrency_probe import claim
PIN=ROOT/'preparations/stop-recovery-20261116/Source-pin.json'
PLAN=ROOT/'plans/stop-recovery-501-502'
KIND='audited-R9-stop-recovery-topology'


def need(ok,message):
    if not ok:raise PermissionError(message)


def accounting(pin):
    ids=list(pin['accounting'])
    q=subprocess.run(['squeue','-h','-u','qiuqian','-o','%i|%T'],check=True,capture_output=True,text=True,timeout=30)
    active={x.split('|')[0].strip() for x in q.stdout.splitlines()};need(not (active & set(ids)),'original/follow job still active')
    a=subprocess.run(['sacct','-n','-P','-j',','.join(ids),'--format=JobIDRaw,State,ExitCode'],check=True,capture_output=True,text=True,timeout=30)
    rows={x.split('|')[0]:x.split('|')[1:3] for x in a.stdout.splitlines() if len(x.split('|'))>=3 and x.split('|')[0] in ids}
    need(rows==pin['accounting'],'exact known terminal accounting required; unknown is not zero/completed')
    return {'queue':q.stdout,'accounting':a.stdout}


def original_sources(parent,pin,p):
    need(sha(parent/'release.json')==pin['R9_release_sha256'],'R9 release changed')
    for n,h in p['source_files'].items():need(sha(parent/n)==h,'R9 frozen source changed: '+n)
    allowed={'experiments/triad/runtime.py','experiments/triad/shared_admission.py','experiments/triad/parallel.py'}
    for n,h in p['source_files'].items():
        if n not in allowed:need(sha(ROOT/n)==h,'scientific/V5/Prompt/evaluator source differs: '+n)


def audit(parent,*,real_accounting=True,member_root=None,source_check=None,now=None):
    """All outcome proofs come from pinned old bytes; no unknown is reclassified."""
    parent=Path(parent).resolve();pin=read(PIN);now=time.time() if now is None else now
    for n,h in pin['shared_files'].items():need(sha(parent/n)==h,'old shared evidence changed: '+n)
    mp=parent/pin['shared_relative'];m=read(mp);g=read(mp.parent/'gate/ledger.json');sources=[];attempts={};failed=[]
    need(m['global_API_width']==1 and m['total_request_cap']==2040,'old API1/original total cap changed')
    need(not any((mp.parent/'gate'/n).exists() for n in ('metrics.lock','send-turn.lock')),'unknown shared writer/send-turn remains')
    for item in pin['members']:
        base=Path(member_root(item)) if member_root else parent
        for n,h in item['files'].items():need(not (base/n).is_symlink() and sha(base/n)==h,'pinned original run changed: '+n)
        d=base/item['run_relative'];p=read(d/'Protocol.json');s=read(d/'checkpoint.json');j=read(d/'API_attempts.json');r=next(r for r in m['members'] if r['seed']==item['seed'])
        (source_check or original_sources)(parent,pin,p)
        need(sha(d/'Protocol.json')==s['identity']==item['protocol_sha256'],'original protocol identity changed')
        need(s['phase']=='paused' and s['cursor']==item['cursor'] and s['eoh']['operator_cursor']==item['evolution'] and s['eoh']['stage']=='evolution','not the settled paused checkpoint; no phase rewrite')
        need(s['eoh']['initialization_requests']==10 and p['config']['population_size']==10 and p['config']['initialization_policy']=='native_EoH' and p['config']['api_attempt_cap']==1020 and p['config']['evolution_request_cap']==1000,'research protocol differs')
        need(not any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json')),'original run writer/STOP remains')
        need(not (Path(r['config']).parent.parent/'run-gates'/r['run_id']/'generation.lock').exists(),'old inner writer gate remains')
        clock=read(d/'Run_clock.json');need(sha(d/'Run_clock.json')==s['clock_sha256'] and clock['deadline']==clock['start']+p['config']['window_seconds'] and now<clock['deadline']-p['config']['resources']['drain_seconds'],'original deadline expired/changed; never extend')
        need(m['account_exclusion']['valid_until']>=clock['deadline'],'original account exclusion cannot cover original deadline')
        need(not j['halt_reason'] and len(j['api_attempts'])==len(j['requests'])==len(s['tasks'])==s['cursor'],'halt/unknown/orphan original journal')
        need(list(s['tasks'])==[t['id'] for t in read(d/'Tasks.json')[:s['cursor']]] and all(t['status']=='completed' for t in s['tasks'].values()),'uncommitted task; never replay')
        for a in j['api_attempts'].values():
            need(a['number']==1 and a['status'] in ('completed','failed'),'unknown API attempt or retry')
            uid=digest({'member':r['run_id'],'key':a['id']});attempts[uid]=(r['run_id'],a)
            if a['status']=='failed':
                meta=a.get('metadata',{});confirmed=a['send_confirmed'] and meta.get('send_status')=='confirmed' and meta.get('http_status')==522 and meta.get('failure_stage')=='http_receive' and a.get('finished_at') is not None
                notsent=not a['send_confirmed'] and meta.get('send_status')=='not_sent' and meta.get('failure_stage')=='shared_admission'
                need(confirmed or notsent,'genuinely unknown failure cannot be settled by this tool')
                failed.append({'uid':uid,'member':r['run_id'],'request_id':a['id'],'classification':'confirmed_HTTP522' if confirmed else 'confirmed_not_sent','status':'failed','charged':True,'usage':a['usage']})
        for e in s['evaluations'].values():need(e['status']=='completed' and sha(d/e['path'])==e['sha256'],'unknown/changed evaluation; no re-solve')
        fields=set(read(ROOT/'experiments/triad/configs/fjsp-eoh.json'))|{'shared_manifest'}
        c={k:v for k,v in p['config'].items() if k in fields};c['real_requests_authorized']=False
        # Reconstituted old config is identity checked; no credentials are read.
        old_config=parent/Path(r['config']).relative_to(pin['parent_root'])
        if old_config.exists():need(sha(old_config)==r['config_sha256'],'old config file changed')
        raw=(json.dumps(c,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
        need(__import__('hashlib').sha256(raw).hexdigest()==r['config_sha256']==p['config_sha256'],'original config cannot be exactly reconstructed')
        sources.append({'item':item,'base':base,'directory':d,'protocol':p,'state':s,'journal':j,'row':r,'config':c})
    need(len(attempts)==1167 and len(failed)==6 and sum(f['classification']=='confirmed_HTTP522' for f in failed)==1 and sum(f['classification']=='confirmed_not_sent' for f in failed)==5,'only the specific one522/five not-sent case is admitted')
    need(len(g['requests'])==1163 and sum(r['state']=='completed' for r in g['requests'].values())==1161,'shared history count changed')
    missing=set(attempts)-set(g['requests']);need(len(missing)==4,'local-only budget differences changed')
    for uid,(member,a) in attempts.items():
        if uid in g['requests']:
            r=g['requests'][uid];need(r['member']==member and r['key']==a['id'],'shared/journal identity differs')
            if a['status']=='completed':need(r['state']=='completed' and a['send_confirmed'],'response settlement differs')
        else:need(a['status']=='failed' and a.get('metadata',{}).get('send_status')=='not_sent','missing shared actual/unknown send')
    need(set(g['active'])=={f['uid'] for f in failed if f['classification']=='confirmed_HTTP522'},'unexplained live permit')
    need(set(g['jobs'])=={r['run_id'] for r in m['members']},'unexplained search owner')
    receipts=accounting(pin) if real_accounting else {'scope':'offline fixture; scheduler not queried'}
    return m,g,sources,failed,attempts,receipts


def descriptor(p,b):return previous.transport_identity(p,b)


def journal(adapter,d,s,p,deadline,*,identity_only=False):
    v=p['stop_recovery']
    if identity_only:
        b=shared.binding(p['config']['shared_manifest'],d,v['config_path']);transport=previous.IdentityOnly(descriptor(p,b))
    else:
        inner=adapter.transport(p);inner.rejection_directory=Path(d)/'caller_rejections'
        transport=DeadlineTransport(WireRecorder(inner,Path(d)/'wire_responses',verify=lambda:adapter.check_run(d)),deadline)
    return StopAwareJournal(Path(d)/'API_attempts.json',config=adapter.client_config(p),context=s['identity'],phase=v['journal_phase'],transport=transport)


def verify_legacy_gate(folder):
    folder=Path(folder)
    if not (folder/'gate/ledger.json').exists():
        need(not (folder/'Prepared.json').exists(),'prepared recovery lost its ledger');return
    if not (folder/'Reconciliation.json').exists():
        need(not (folder/'Prepared.json').exists(),'prepared recovery lost reconciliation');return
    rec=read(folder/'Reconciliation.json');oldpath=folder/'parent-evidence/gate/ledger.json'
    need(sha(oldpath)==rec['parent_gate_sha256'],'archived old shared ledger changed')
    if (folder/'Prepared.json').exists():need(read(folder/'Prepared.json')['reconciliation_sha256']==sha(folder/'Reconciliation.json'),'reconciliation changed after preparation')
    old=read(oldpath);g=read(folder/'gate/ledger.json');failures={r['uid']:r for r in rec['failures']}
    need(len(failures)==6 and rec['charged_requests_before']==rec['charged_requests_after']==1167,'reconciliation must preserve1167 charges/six failures')
    for uid,r in old['requests'].items():
        need(uid in g['requests'],'old shared charge removed')
        if uid not in failures:need(g['requests'][uid]==r,'old successful settlement altered')
    for uid,failure in failures.items():
        need(uid in g['requests'],'failed charged slot missing')
        r=g['requests'][uid]
        need(r['state']=='reconciled_failed' and r['charged'] is True and r['member']==failure['member'] and r['key']==failure['request_id'] and r['outcome']==failure,'known failed terminal outcome altered/declared successful')
        if uid not in old['requests']:need(r.get('administrative_import_of_already_charged_not_sent') is True and 'sent_at' not in r,'local-only slot cannot become a fabricated send')
    need(len(set(old['requests'])|set(failures))==1167 and len(g['requests'])>=1167,'legacy budget identity differs')


def verify(d,p):
    d=Path(d);v=p['stop_recovery'];need(v['source_pin_sha256']==sha(PIN),'recovery source pin changed')
    for n,h in v['immutable_evidence'].items():need(sha(d/n)==h,'original failure/clock/checkpoint evidence changed: '+n)
    need(sha(d/'Run_clock.json')==v['original_clock_sha256'],'original clock changed')
    old=read(d/'parent-evidence/API_attempts.json');current=read(d/'API_attempts.json')
    for field in ('requests','api_attempts'):need(all(current[field].get(k)==value for k,value in old[field].items()),'inherited attempt altered/refunded/replayed')
    verify_legacy_gate(Path(p['config']['shared_manifest']).parent)
    need(p['config']['initialization_policy']=='native_EoH' and p['config']['population_size']==10 and p['config']['api_attempt_cap']==1020 and p['config']['evolution_request_cap']==1000,'science/budget changed')


def prepare(parent,*,real_accounting=True,member_root=None,source_check=None,now=None):
    parent=Path(parent).resolve();now=time.time() if now is None else now
    if (PLAN/'Prepared.json').exists():return {'already_prepared':True,**inspect()}
    need(not PLAN.exists(),'partial/unknown preparation retained; do not overwrite/retry')
    m,g,sources,failures,attempts,receipts=audit(parent,real_accounting=real_accounting,member_root=member_root,source_check=source_check,now=now)
    claim(PLAN/'Preparation-reservation.json',{'parent':str(parent),'source_pin_sha256':sha(PIN),'at':now,'automatic_retry':False})
    path=PLAN/'Shared.json';newm=copy.deepcopy(m);newm.update(version=shared.VERSION,batch_id='fjsp-audited-stop-recovery-20261116',members=[])
    for item in sources:
        r=copy.deepcopy(item['row']);c=copy.deepcopy(item['config'])
        for key in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results'):
            if c.get(key):c[key]=str(ROOT/Path(c[key]).relative_to(read(PIN)['parent_root']))
        c.update(shared_manifest=str(path),account_gate=str(PLAN/'run-gates'/r['run_id']))
        config=PLAN/'configs'/(r['run_id']+'.json');write(config,c)
        r.update(config=str(config),config_sha256=sha(config),child_config_sha256=sha(config),run_dir=str(ROOT/'runs'/PLAN.name/r['run_id']))
        need(not Path(r['run_dir']).exists(),'recovery run exists; never reinitialize')
        newm['members'].append(r);item['newrow']=r
    write(path,newm);shared.load(path)
    for item in sources:
        r=item['newrow'];d=Path(r['run_dir']);old=item['directory'];oldp=item['protocol'];olds=item['state']
        p=runtime.prepare(d,r['config'],allow_api=True,approve_budget=1020)
        need(p['instances']==oldp['instances'] and p['references']==oldp['references'] and p['H_prompt_contract']==oldp['H_prompt_contract'] and p['metrics']==oldp['metrics'],'scientific inputs/Prompt/score changed')
        ev=d/'parent-evidence';ev.mkdir()
        for name in ('Protocol.json','Protocol.sha256','checkpoint.json','API_attempts.json','Run_clock.json','latest-submission.json'):shutil.copyfile(old/name,ev/name)
        for name in ('worker-receipts','evaluations','prompts','responses','wire_responses','caller_rejections','populations'):
            if (old/name).exists():shutil.copytree(old/name,d/name)
        # Previous R8 ancestry is retained; old R9 directory/ZIP also remain untouched.
        if (old/'parent-evidence').exists():shutil.copytree(old/'parent-evidence',ev/'previous-ancestry')
        shutil.copyfile(old/'Run_clock.json',d/'Run_clock.json')
        phases={a['id'].split('/SLOT-')[0] for a in item['journal']['api_attempts'].values()};need(len(phases)==1,'mixed original journal namespaces')
        p['stop_recovery']={'version':'audited-settled-failure-import-v1','source_pin_sha256':sha(PIN),'parent_protocol_sha256':olds['identity'],'parent_job_id':item['item']['job_id'],'config_path':r['config'],'journal_phase':next(iter(phases)),'inherited_requests':len(item['journal']['api_attempts']),'inherited_solves':item['item']['solves'],'original_clock_sha256':sha(old/'Run_clock.json'),'original_eoh_sha256':digest(olds['eoh']),'original_cursor':olds['cursor'],'original_phase':'paused','immutable_evidence':{str(f.relative_to(d)):sha(f) for f in ev.iterdir() if f.is_file()},'no_refund':True,'no_replay':True,'no_reinitialization':True,'current_RNG_preserved_not_P000':True}
        write(d/'Protocol.json',p);(d/'Protocol.sha256').write_text(sha(d/'Protocol.json')+'\n')
        fresh=read(d/'checkpoint.json')
        for key in ('cursor','tasks','evaluations','population','children','seen','generation','generations','u_rng','u_plan','rng','transport_failure_streak','eoh'): 
            if key in olds:fresh[key]=copy.deepcopy(olds[key])
        fresh.update(identity=sha(d/'Protocol.json'),clock_sha256=sha(d/'Run_clock.json'))
        write(d/'checkpoint.json',fresh)
        j=journal(runtime.Adapter(),d,fresh,p,read(d/'Run_clock.json')['deadline'],identity_only=True)
        j.data.update(requests=copy.deepcopy(item['journal']['requests']),api_attempts=copy.deepcopy(item['journal']['api_attempts']),inherited_from_protocol=olds['identity']);j.save()
        shared.attach(d,shared.binding(path,d,r['config']))
        runtime.Adapter().check_run(d)
    newg=copy.deepcopy(g);newg.update(version=shared.VERSION,manifest_sha256=sha(path),active={},jobs={})
    by_uid={f['uid']:f for f in failures}
    for uid,(member,a) in attempts.items():
        if uid not in newg['requests']:
            newg['requests'][uid]={'member':member,'key':a['id'],'ticket':newg['next_ticket'],'reserved_at':a['started_at'],'administrative_import_of_already_charged_not_sent':True};newg['next_ticket']+=1
        if uid in by_uid:
            newg['requests'][uid].update(state='reconciled_failed',outcome=by_uid[uid],charged=True,original_state=g['requests'].get(uid,{}).get('state','local_journal_only'))
            shared.Admission.event(newg,'reconciled_terminal',uid=uid,member=member,classification=by_uid[uid]['classification'],successful_response=False,refund=False)
    need(len(newg['requests'])==1167 and sum(x['state']=='reconciled_failed' for x in newg['requests'].values())==6,'recovery lost a charged failure')
    claim(PLAN/'gate/ledger.json',newg)
    evidence=PLAN/'parent-evidence';evidence.mkdir()
    for name in ('Shared.json','Acceptance.json','gate/ledger.json','gate/STOP.json'):
        target=evidence/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(parent/Path(read(PIN)['shared_relative']).parent/name,target)
    claim(PLAN/'Reconciliation.json',{'version':'explicit-known-failure-settlement-v1','parent_manifest_sha256':sha(parent/read(PIN)['shared_relative']),'parent_gate_sha256':sha(parent/Path(read(PIN)['shared_relative']).parent/'gate/ledger.json'),'failures':failures,'charged_requests_before':1167,'charged_requests_after':1167,'shared_records_before':1163,'shared_records_after':1167,'billing_for_HTTP522':'unknown; no refund or assertion of charge','old_STOP_preserved':True,'all_old_bytes_preserved':True,'no_new_API':True,'accounting_evidence':receipts})
    claim(PLAN/'Acceptance.json',{'kind':KIND,'manifest_sha256':sha(path),'adapter_sha256':sha(shared.__file__),'validated_nodes':['node15','node15'],'real_dispatch_path_verified':False,'new_compute_verification':False,'finite_actual_acceptance_required':True,'scope':'historical R9 same-node API1; new known-failure closure/STOP path offline only; real finite continuation still required'})
    claim(PLAN/'Prepared.json',{'manifest_sha256':sha(path),'parent':str(parent),'at':now,'inherited_requests':1167,'reconciliation_sha256':sha(PLAN/'Reconciliation.json'),'finite_new_requests_upper':2,'finite_new_solves_upper':84})
    return inspect()


def inspect():
    m=shared.load(PLAN/'Shared.json');need(read(PLAN/'Prepared.json')['manifest_sha256']==sha(PLAN/'Shared.json'),'incomplete recovery preparation')
    rows=[]
    for r in m['members']:
        d=Path(r['run_dir']);a=runtime.Adapter();p=a.check_run(d);s=read(d/'checkpoint.json');execution.ledger(d,s,p,adapter=a)
        j=journal(a,d,s,p,read(d/'Run_clock.json')['deadline'],identity_only=True)
        rows.append({'seed':r['seed'],'run_id':r['run_id'],'phase':s['phase'],'cursor':s['cursor'],'evolution_attempts':s['eoh']['operator_cursor'],'remaining_evolution':1000-s['eoh']['operator_cursor'],'charged_requests':j.attempt_count,'remaining_original_request_cap':1020-j.attempt_count,'native_generation':s['eoh']['native_generation'],'next_population_records':len(s['eoh']['next_population']),'original_clock':read(d/'Run_clock.json')})
    g=read(PLAN/'gate/ledger.json')
    return {'manifest':str(PLAN/'Shared.json'),'members':rows,'shared_charged':len(g['requests']),'shared_states':{k:sum(x['state']==k for x in g['requests'].values()) for k in ('completed','reconciled_failed','waiting','admitted','sent','failed_or_unknown')},'STOP':(PLAN/'gate/STOP.json').exists(),'API_requests_by_inspection':0,'solves_by_inspection':0}


def activate(parent,ack=False,*,real_accounting=True,member_root=None,source_check=None):
    need(ack,'explicit acknowledgment of one522/five not-sent, all budgets retained required')
    info=inspect();path=PLAN/'Shared.json';m=shared.load(path);pin=read(PIN);parent=Path(parent).resolve();lease=Path(m['account_gate'])/'generation.lock'
    identity={'protocol':'SHARED:'+sha(path),'batch':str(path),'version':shared.VERSION}
    if (PLAN/'Activation.json').exists():
        a=read(PLAN/'Activation.json');need(a.get('state')=='active' and read(lease)==identity,'partial/unknown handoff retained; no automatic repair')
        return {'already_activated':True,'API_requests':0,'actual_solves':0}
    audit(parent,real_accounting=real_accounting,member_root=member_root,source_check=source_check)
    old_manifest=parent/pin['shared_relative'];old=read(lease)
    need(old.get('protocol')=='SHARED:'+sha(old_manifest) and old.get('batch')==str(old_manifest),'not this old account lease; never clear a different owner')
    need(not (PLAN/'gate/STOP.json').exists(),'new recovery STOP; never auto-clear')
    need(all(r['phase']=='prepared' for r in info['members']),'recovery already started or unknown')
    registry=Path(m['account_gate'])/'continuations'/sha(old_manifest)
    need(not registry.exists(),'parent already reserved for another recovery')
    claim(registry,{'state':'recovery_reserved','new_manifest':str(path),'reconciliation_sha256':sha(PLAN/'Reconciliation.json'),'parent_manifest_sha256':sha(old_manifest),'automatic_retry':False})
    old_bytes=lease.read_bytes();archive=PLAN/'parent-evidence/account-lease.json'
    with archive.open('xb') as file:file.write(old_bytes);file.flush();os.fsync(file.fileno())
    claim(PLAN/'Activation.json',{'state':'handoff_reserved','old_lease':old,'old_lease_sha256':sha(archive),'identity':identity,'reconciliation_sha256':sha(PLAN/'Reconciliation.json')})
    claim(old_manifest.parent/'Recovery-retired-to-r11.json',{'new_manifest':str(path),'reconciliation_sha256':sha(PLAN/'Reconciliation.json'),'old_STOP_and_ledger_preserved':True,'at':time.time()})
    # This is an explicit owned handoff, not deletion of unknown locks/STOP.
    need(read(lease)==old,'account ownership changed during handoff')
    replacement=Path(m['account_gate'])/('owned-recovery-'+sha(path)+'.pending-owner')
    claim(replacement,identity)
    need(lease.read_bytes()==old_bytes,'account lease bytes changed before atomic owned handoff')
    os.replace(replacement,lease)
    fd=os.open(lease.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    write(PLAN/'Activation.json',{'state':'active','old_lease':old,'old_lease_sha256':sha(archive),'identity':identity,'reconciliation_sha256':sha(PLAN/'Reconciliation.json'),'at':time.time()})
    return {'activated':True,'old_STOP_preserved':True,'old_requests_refunded':0,'API_requests':0,'actual_solves':0}


def finite_submit(approved=False):
    need(approved,'explicit2 requests/84 inclusive solves within original2040 required')
    if (PLAN/'Finite-submitted.json').exists():return {'already_submitted':True,**read(PLAN/'Finite-submitted.json')}
    need(not (PLAN/'Finite-reservation.json').exists(),'unknown finite submission retained; no retry')
    m=shared.load(PLAN/'Shared.json');prefixes={r['index']:read(Path(r['run_dir'])/'Protocol.json')['stop_recovery']['original_cursor']+1 for r in m['members']}
    info=inspect();need(all(r['phase']=='prepared' and r['cursor']+1==prefixes[i] for i,r in enumerate(info['members'])),'finite continuation starts from imported cursor exactly once')
    parallel.submit(PLAN/'Shared.json','run',False,prefix=prefixes,solve_cap=84)
    claim(PLAN/'Finite-reservation.json',{'manifest_sha256':sha(PLAN/'Shared.json'),'prefixes':prefixes,'maximum_new_requests':2,'maximum_new_solves_including_recheck':84,'automatic_retry':False})
    result=parallel.submit(PLAN/'Shared.json','run',True,2040,True,True,prefixes,84)
    write(PLAN/'Finite-submitted.json',result);return result


def verify_acceptance(path,certificate,require_finite=False):
    path=Path(path);need(certificate.get('kind')==KIND and certificate['manifest_sha256']==sha(path) and certificate['adapter_sha256']==sha(shared.__file__),'audited recovery/topology binding changed')
    need(sha(PLAN/'Reconciliation.json')==read(PLAN/'Activation.json')['reconciliation_sha256'],'reconciliation/handoff changed')
    if require_finite:
        a=read(PLAN/'Finite-accepted.json');need(a['manifest_sha256']==sha(path) and a['adapter_sha256']==sha(shared.__file__) and a['passed'] and a['maximum_new_requests']==2 and a['original_budget_retained'],'new-version finite actual acceptance required')
    return True


def certify():
    if (PLAN/'Finite-accepted.json').exists():return {'already_certified':True,**read(PLAN/'Finite-accepted.json')}
    info=inspect();m=shared.load(PLAN/'Shared.json');g=read(PLAN/'gate/ledger.json');need(not info['STOP'] and not g['active'] and not g['jobs'],'new STOP/unknown/active; no full continuation')
    shared.Admission({'manifest':str(PLAN/'Shared.json'),'sha256':sha(PLAN/'Shared.json'),'run_id':m['members'][0]['run_id']}).verify()
    jobs=[];solves=0
    for r in m['members']:
        d=Path(r['run_dir']);p=read(d/'Protocol.json');s=read(d/'checkpoint.json');j=read(d/'API_attempts.json');v=p['stop_recovery'];receipt=read(d/'latest-submission.json');job=receipt.get('job_id','')
        need(not any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json')) and not (Path(p['config']['account_gate'])/'generation.lock').exists(),'finite writer/STOP remains')
        need(s['phase']=='paused' and s['cursor']==v['original_cursor']+1 and len(j['api_attempts'])==v['inherited_requests']+1,'finite step must settle exactly one new opportunity')
        need(receipt.get('state')=='submitted' and job.isdigit(),'unknown finite submission')
        a=subprocess.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode,NodeList'],check=True,text=True,capture_output=True,timeout=30)
        observed=next((x.split('|')[:4] for x in a.stdout.splitlines() if x.split('|')[0]==job),None)
        need(observed==[job,'COMPLETED','0:0','node15'],'actual successful bounded same-node accounting required')
        ready=read(PLAN/'preflight'/('ready-'+str(r['index'])+'.json'));need(ready['job_id']==job and read(PLAN/'preflight'/('fs-pass-'+str(r['index'])+'.json'))['passed'],'new actual filesystem checks missing')
        task=s['tasks'][f'SLOT-{v["original_cursor"]:07d}'];need(task['valid'] and task.get('failure') is None,'finite scientific failure retained; do not refill or auto-continue')
        attempt=next(a for a in j['api_attempts'].values() if a['logical_id']==task['id']);meta=attempt['reply']['metadata'] if attempt['status']=='completed' else {}
        need(not meta.get('mock') and not meta.get('engineering_only'),'synthetic response cannot certify actual continuation')
        need(attempt['status']=='completed' and attempt['send_confirmed'] and meta.get('http_status')==200 and meta.get('finish_reason')=='stop' and meta.get('model')==p['config']['provider']['expected_response_model'],'finite actual strict response failed')
        summary=runtime.Adapter().summary(d);completed=sum(summary['physical_passes'][x]['completed'] for x in ('first','recheck'));delta=completed-v['inherited_solves'];need(0<=delta<=42,'extra first/recheck solves outside finite budget');solves+=delta;jobs.append(job)
    need(len(set(jobs))==2 and len(g['requests'])==1169 and sum(x['state']=='reconciled_failed' for x in g['requests'].values())==6 and g['peak']==1 and parallel.sent_peak(g)==1,'finite global charge/failure/API1 accounting differs')
    result={'passed':True,'manifest_sha256':sha(PLAN/'Shared.json'),'adapter_sha256':sha(shared.__file__),'actual_two_Slurm_jobs':jobs,'validated_nodes':['node15','node15'],'maximum_new_requests':2,'actual_new_requests':2,'actual_new_solves_including_recheck':solves,'maximum_new_solves_including_recheck':84,'original_budget_retained':True,'API_width':1,'provider_maximum_claim':False}
    claim(PLAN/'Finite-accepted.json',result);return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['prepare','check-only','activate','finite-submit','certify']);ap.add_argument('--parent-root',type=Path,default=Path(read(PIN)['parent_root']));ap.add_argument('--acknowledge-known-failures-keep-budget',action='store_true');ap.add_argument('--submit',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-requests',type=int);ap.add_argument('--approve-new-requests',type=int);ap.add_argument('--approve-new-solves',type=int);a=ap.parse_args()
    approved=a.submit and a.allow_api and a.allow_solves and a.approve_requests==2040 and a.approve_new_requests==2 and a.approve_new_solves==84
    value=prepare(a.parent_root) if a.action=='prepare' else inspect() if a.action=='check-only' else activate(a.parent_root,a.acknowledge_known_failures_keep_budget) if a.action=='activate' else finite_submit(approved) if a.action=='finite-submit' else certify()
    print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
