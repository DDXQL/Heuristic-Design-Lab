#!/usr/bin/env python3
"""Explicit, one-time settled-state import. Search, HTTP and solvers are NOT implemented here."""
import argparse
import copy
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.llm.legacy import WireRecorder,DeadlineTransport
from heuristic_design.llm.strict_nonstream import StopAwareJournal,POLICY
from fjsp_usage.research_real.real_transport import WIRE_VERSION,OBSERVATION_VERSION
from experiments.triad import runtime,configuration,shared_admission as shared
from experiments.triad.concurrency_probe import claim
PIN=ROOT/'preparations/native-continuation-20261115/parent-pin.json'
AMENDMENT=ROOT/'preparations/native-continuation-20261115/Amendment.json'
PLAN=ROOT/'plans/native-eoh-501-502'
KIND='inherited_admission_not_new_compute_verification'


def require(ok,message):
    if not ok:raise ValueError(message)


def parent_audit(parent,*,accounting=True,now=None):
    """Read only the two explicitly pinned, settled parent runs."""
    parent=Path(parent).resolve();pin=read(PIN);now=time.time() if now is None else now
    for n,h in pin['shared_files'].items():require(sha(parent/n)==h,'parent shared evidence changed: '+n)
    m=read(parent/pin['parent_plan']);gate=read(parent/'plans/first-eoh-501-502/gate/ledger.json')
    require(not gate['active'] and not gate['jobs'] and len(gate['requests'])==20 and all(r['state']=='completed' for r in gate['requests'].values()),'unknown or active parent requests')
    require(not any((parent/'plans/first-eoh-501-502/gate'/n).exists() for n in ('STOP.json','metrics.lock','send-turn.lock')),'parent shared stop/writer retained')
    audited=[]
    for item in pin['members']:
        for n,h in item['files'].items():
            f=parent/n;require(not f.is_symlink() and sha(f)==h,'parent evidence changed: '+n)
        d=parent/item['run_relative'];p=read(d/'Protocol.json');s=read(d/'checkpoint.json');j=read(d/'API_attempts.json');v=read(d/'populations/P000_initial.json');clock=read(d/'Run_clock.json')
        require(s['identity']==sha(d/'Protocol.json') and s['phase']=='initialization_incomplete' and s['cursor']==10,'parent failure identity/cursor changed')
        require(clock['deadline']==clock['start']+p['config']['window_seconds'] and now<clock['deadline'],'original deadline expired/changed; no extension')
        require(s['clock_sha256']==sha(d/'Run_clock.json'),'clock bytes changed')
        require(p['config']['group']=='fjsp-eoh' and p['config']['initialization_policy']=='native_N_finite_or_fail' and p['config']['search_seed']==item['seed'],'wrong source policy/seed')
        require(p['config']['population_size']==10 and p['config']['api_attempt_cap']==1020 and p['config']['initialization_request_cap']==20 and p['config']['evolution_request_cap']==1000,'original budget changed')
        require(v['stage']=='evolution' and v['native_generation']==2 and v['operator_cursor']==0 and v['initialization_requests']==10 and v['population']==s['eoh']['population'] and not v['next_population'],'initial native snapshot differs')
        require(len(j['requests'])==len(j['api_attempts'])==len(s['tasks'])==10 and not j['halt_reason'] and all(r['status']=='completed' for r in j['requests'].values()) and all(a['status']=='completed' and a['send_confirmed'] and a['number']==1 for a in j['api_attempts'].values()),'unknown/failed request; no replay')
        require(all(t['status']=='completed' and t['valid'] and t['operator']=='I1' for t in s['tasks'].values()),'unsettled initialization')
        require(not any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json')),'parent writer/stop retained')
        row=next(r for r in m['members'] if r['seed']==item['seed'])
        require(sha(parent/Path(row['config']).relative_to(read(PIN)['parent_root']))==row['config_sha256'],'parent config changed')
        require(not (Path(row['config']).parent.parent/'run-gates'/row['run_id']/'generation.lock').exists(),'parent inner writer gate retained')
        # Numerical replay only: native rank sampling, no H or response execution.
        import numpy as np
        finite=sorted([r for r in v['population'] if not r['negative_infinity'] and r['score'] is not None and math.isfinite(r['score'])],key=lambda r:r['score'],reverse=True)
        require(len(finite)==(8 if item['seed']==501 else 9),'finite parent count differs')
        rng=np.random.RandomState();st=v['np_rng'];rng.set_state((st[0],np.asarray(st[1],dtype=np.uint32),st[2],st[3],st[4]))
        weights=np.array([1/(rank+len(finite)) for rank in range(len(finite))]);weights/=weights.sum()
        selected=[finite[int(rng.choice(len(finite),p=weights))]['id'] for _ in range(2)]
        st=rng.get_state();after=[st[0],st[1].tolist(),int(st[2]),int(st[3]),float(st[4])]
        require(after==s['eoh']['np_rng'],'unsubmitted first-E1 draws not exactly explained')
        for ev in s['evaluations'].values():require(ev['status']=='completed' and sha(d/ev['path'])==ev['sha256'],'unsettled/changed evaluation')
        if accounting:
            receipt=read(d/'latest-submission.json');require(receipt.get('state')=='submitted' and receipt.get('job_id')==item['job_id'],'unknown parent submission')
            receipts=list((d/'submissions').glob('*.json'))
            require(all(str(f.relative_to(parent)) in item['files'] for f in receipts),'new/unknown parent submission receipt; no continuation')
            saved=[read(f) for f in receipts]
            require(saved and all(r.get('state')=='submitted' and str(r.get('job_id','')).isdigit() for r in saved),'unknown parent submission; no continuation')
            ids={r['job_id'] for r in saved};ids.add(item['job_id'])
            a=subprocess.run(['sacct','-n','-P','-j',','.join(sorted(ids)),'--format=JobIDRaw,State,ExitCode'],check=True,text=True,capture_output=True)
            records={line.split('|')[0]:line.split('|')[:3] for line in a.stdout.splitlines() if line.split('|')[0] in ids}
            require(set(records)==ids and all(r[1].split()[0] in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'} for r in records.values()),'parent submission active/accounting unknown')
            require(records[item['job_id']]==[item['job_id'],'FAILED','2:0'],'parent accounting not the pinned settled failure')
        audited.append({'item':item,'directory':d,'protocol':p,'state':s,'journal':j,'snapshot':v,'first_E1_parents':selected,'row':row})
    # Same original scientific code and inputs, except precisely these administrative adapters.
    allowed={'experiments/triad/runtime.py','experiments/triad/parallel.py','experiments/triad/build.py','experiments/triad/cluster.py','experiments/triad/launch_concurrent.py'}
    for n,h in pin['parent_release']['files'].items():
        if n.startswith(('code/','experiments/common/','deploy/eoh-baseline/')) or n in audited[0]['protocol']['source_files']:
            if n not in allowed:require(sha(ROOT/n)==h,'scientific source differs: '+n)
    return m,gate,audited


def transport_identity(p,b):
    """Public identity only; never instantiate a real client or read credentials."""
    c=runtime.Adapter().client_config(p)
    base=digest({'provider':c.payload()['provider'],'mode':c.mode,'transport_version':WIRE_VERSION,'observation_version':OBSERVATION_VERSION})
    strict=digest({'common_wire_identity':base,'caller_acceptance_policy':POLICY})
    return digest({'transport':strict,'shared':b,'version':shared.VERSION})


class IdentityOnly:
    def __init__(self,identity):self.identity=identity
    def dispatch(self,*args,**kwargs):raise PermissionError('offline identity descriptor cannot send')


def journal(adapter,d,s,p,deadline,*,identity_only=False):
    lineage=p['continuation'];phase='operations/'+lineage['parent_protocol_sha256']
    if identity_only:
        b=shared.binding(p['config']['shared_manifest'],d,lineage['config_path'])
        transport=IdentityOnly(transport_identity(p,b))
    else:
        inner=adapter.transport(p);inner.rejection_directory=Path(d)/'caller_rejections'
        wire=WireRecorder(inner,Path(d)/'wire_responses',verify=lambda:adapter.check_run(d))
        transport=DeadlineTransport(wire,deadline)
    return StopAwareJournal(Path(d)/'API_attempts.json',config=adapter.client_config(p),context=s['identity'],phase=phase,transport=transport)


def verify(directory,p):
    d=Path(directory);v=p['continuation']
    require(v['amendment_sha256']==sha(AMENDMENT) and v['parent_pin_sha256']==sha(PIN),'continuation decision/pin changed')
    require(p['config']['initialization_policy']=='native_EoH' and p['config']['population_size']==10 and p['config']['api_attempt_cap']==1020 and p['config']['evolution_request_cap']==1000,'amended policy/budget changed')
    for n,h in v['inherited_files'].items():require(sha(d/n)==h,'inherited evidence changed: '+n)
    require(sha(d/'Run_clock.json')==v['original_clock_sha256'],'original clock changed')
    old=read(d/'parent-evidence/API_attempts.json');current=read(d/'API_attempts.json')
    for field in ('requests','api_attempts'):
        require(all(current[field].get(k)==value for k,value in old[field].items()),'inherited charged request altered/refunded')
    require(read(d/'parent-evidence/checkpoint.json')['phase']=='initialization_incomplete','original failure lost')


def verify_inherited_acceptance(path,certificate):
    path=Path(path);m=shared.load(path)
    require(certificate.get('kind')==KIND and certificate.get('real_dispatch_path_verified') is False,'not a typed inherited admission')
    require(certificate['manifest_sha256']==sha(path) and certificate['adapter_sha256']==sha(shared.__file__),'inherited admission binding changed')
    parent=read(path.parent/'parent-evidence/Acceptance.json')
    require(sha(path.parent/'parent-evidence/Acceptance.json')==certificate['parent_certificate_sha256'] and parent['real_dispatch_path_verified'] and parent['validated_nodes']==certificate['validated_nodes'],'parent actual admission proof changed')
    require(parent['adapter_sha256']==sha(shared.__file__) and parent['manifest_sha256']==read(PIN)['shared_files']['plans/first-eoh-501-502/Shared.json'],'shared gate or original proof changed')
    for r in m['members']:
        p=runtime.Adapter().check_run(Path(r['run_dir']));require('continuation' in p,'inherited admission only for audited continuation')
    return True


def prepare(parent,*,accounting=True,now=None):
    now=time.time() if now is None else now
    pm,pg,parents=parent_audit(parent,accounting=accounting,now=now)
    require(pm['account_exclusion']['valid_until']>=max(read(x['directory']/'Run_clock.json')['deadline'] for x in parents),'original exclusion does not cover deadline')
    require(not PLAN.exists(),'continuation target/reservation already exists; inspect, never reimport')
    # A durable reservation is first. Interrupted/partial preparation must NOT be rerun.
    claim(PLAN/'Import-reservation.json',{'state':'reserved','parent':str(parent),'pin_sha256':sha(PIN),'at':now,'automatic_retry':False})
    manifest=PLAN/'Shared.json';m=copy.deepcopy(pm);m.update(batch_id='native-eoh-continuation-20261115',members=[])
    for source in parents:
        oldrow=source['row'];r=copy.deepcopy(oldrow);c=read(Path(parent)/Path(oldrow['config']).relative_to(read(PIN)['parent_root']))
        c['initialization_policy']='native_EoH';c['protocol_receipt']={**c['protocol_receipt'],'native_admission_amendment_sha256':sha(AMENDMENT),'applies_to_all_FJSP_EoH_seeds':[501,502,503]}
        for key in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results'):
            if c.get(key):c[key]=str(ROOT/Path(c[key]).relative_to(read(PIN)['parent_root']))
        c.update(shared_manifest=str(manifest),account_gate=str(PLAN/'run-gates'/r['run_id']))
        config=PLAN/'configs'/(r['run_id']+'.json');write(config,c)
        r.update(config=str(config),config_sha256=sha(config),child_config_sha256=sha(config),run_dir=str(ROOT/'runs'/PLAN.name/r['run_id']))
        require(not Path(r['run_dir']).exists(),'continuation run already exists; no replacement')
        m['members'].append(r);source['newrow']=r
    write(manifest,m);shared.load(manifest)
    for source in parents:
        row=source['newrow'];d=Path(row['run_dir']);original=source['directory'];oldp=source['protocol'];olds=source['state']
        p=runtime.prepare(d,row['config'],allow_api=True,approve_budget=1020)
        require(p['instances']==oldp['instances'] and p['references']==oldp['references'] and p['H_prompt_contract']==oldp['H_prompt_contract'] and p['metrics']==oldp['metrics'],'scientific input/Prompt/score changed')
        # Copy settled evidence only, never old control files, locks, leases, submissions or active phase.
        evidence=d/'parent-evidence'
        for name in ('Protocol.json','Protocol.sha256','checkpoint.json','API_attempts.json','Run_clock.json','latest-submission.json'):
            evidence.mkdir(exist_ok=True);shutil.copyfile(original/name,evidence/name)
        for name in ('worker-receipts','evaluations','prompts','responses','wire_responses','caller_rejections'):
            if (original/name).exists():shutil.copytree(original/name,d/name)
        shutil.copytree(original/'populations',evidence/'populations')
        (d/'populations').mkdir();shutil.copyfile(original/'populations/P000_initial.json',d/'populations/P000_initial.json')
        shutil.copyfile(original/'Run_clock.json',d/'Run_clock.json')
        inherited={str(f.relative_to(d)):sha(f) for f in d.rglob('*') if f.is_file() and f.name not in ('Protocol.json','Protocol.sha256','checkpoint.json','Tasks.json')}
        # Include original identity files even though their basenames are excluded above.
        inherited.update({str(f.relative_to(d)):sha(f) for f in evidence.rglob('*') if f.is_file()})
        p['continuation']={'version':'settled-native-eoh-import-v1','logical_run_id':row['run_id'],'config_path':row['config'],'parent_protocol_sha256':olds['identity'],'parent_job_id':source['item']['job_id'],'parent_pin_sha256':sha(PIN),'amendment_sha256':sha(AMENDMENT),'original_clock_sha256':sha(original/'Run_clock.json'),'inherited_files':inherited,'imported_requests':10,'imported_solves':378 if row['seed']==501 else 420,'first_E1_parents':source['first_E1_parents'],'rng_source':'populations/P000_initial.json; exact two unsubmitted E1 draws accounted','new_initialization_requests':0,'original_failure_preserved':True}
        write(d/'Protocol.json',p);(d/'Protocol.sha256').write_text(sha(d/'Protocol.json')+'\n')
        fresh=read(d/'checkpoint.json')
        # Reconstruct an explicitly prepared revision, not an edit of the failed checkpoint.
        for key in ('cursor','tasks','evaluations','population','children','seen','generation','pause_ack','generations','u_rng','u_plan','rng','transport_failure_streak'):
            if key in olds:fresh[key]=copy.deepcopy(olds[key])
        fresh.update(identity=sha(d/'Protocol.json'),eoh=copy.deepcopy(source['snapshot']),clock_sha256=sha(d/'Run_clock.json'))
        write(d/'checkpoint.json',fresh)
        j=journal(runtime.Adapter(),d,fresh,p,read(d/'Run_clock.json')['deadline'],identity_only=True)
        j.data.update(requests=copy.deepcopy(source['journal']['requests']),api_attempts=copy.deepcopy(source['journal']['api_attempts']),inherited_from=olds['identity']);j.save()
        shared.attach(d,shared.binding(manifest,d,row['config']))
        runtime.Adapter().check_run(d)
    pg=copy.deepcopy(pg);pg['manifest_sha256']=sha(manifest)
    shared.Admission.event(pg,'explicit_protocol_continuation',parent_manifest_sha256=sha(Path(parent)/read(PIN)['parent_plan']),amendment_sha256=sha(AMENDMENT))
    claim(PLAN/'gate/ledger.json',pg)
    evidence=PLAN/'parent-evidence';evidence.mkdir()
    shutil.copyfile(Path(parent)/'plans/first-eoh-501-502/Acceptance.json',evidence/'Acceptance.json')
    shutil.copyfile(Path(parent)/'plans/first-eoh-501-502/Shared.json',evidence/'Shared.json')
    certificate={'kind':KIND,'manifest_sha256':sha(manifest),'adapter_sha256':sha(shared.__file__),'parent_certificate_sha256':sha(evidence/'Acceptance.json'),'validated_nodes':read(evidence/'Acceptance.json')['validated_nodes'],'real_dispatch_path_verified':False,'inherited_admission_verified':True,'new_compute_verification':False,'scope':'unchanged shared gate/V5/Prompt/evaluator, same node topology; fresh filesystem preflight before sending'}
    claim(PLAN/'Acceptance.json',certificate);verify_inherited_acceptance(manifest,certificate)
    claim(PLAN/'Import-complete.json',{'manifest_sha256':sha(manifest),'parent':str(parent),'imported_requests':20,'imported_solves':798,'new_API_requests':0,'new_solves':0,'new_initialization_requests':0,'at':now})
    return inspect()


def inspect():
    manifest=PLAN/'Shared.json';m=shared.load(manifest);rows=[]
    require(read(PLAN/'Import-complete.json')['manifest_sha256']==sha(manifest),'incomplete continuation import')
    verify_inherited_acceptance(manifest,read(PLAN/'Acceptance.json'))
    for r in m['members']:
        d=Path(r['run_dir']);p,s=runtime.protocol_state(d);adapter=runtime.Adapter();adapter.check_run(d)
        from heuristic_design.core import execution
        execution.ledger(d,s,p,adapter=adapter)
        j=journal(runtime.Adapter(),d,s,p,read(d/'Run_clock.json')['deadline'],identity_only=True)
        rows.append({'seed':r['seed'],'phase':s['phase'],'cursor':s['cursor'],'initialization_requests':s['eoh']['initialization_requests'],'evolution_attempts':s['eoh']['operator_cursor'],'charged_requests':j.attempt_count,'remaining_original_cap':1020-j.attempt_count,'native_population':len(s['eoh']['population']),'finite_parents':len(s['population']),'clock':read(d/'Run_clock.json'),'first_E1_parents':p['continuation']['first_E1_parents']})
    g=read(PLAN/'gate/ledger.json');require(len(g['requests'])>=20,'shared budget refund')
    for k,v in read(Path(read(PLAN/'Import-complete.json')['parent'])/'plans/first-eoh-501-502/gate/ledger.json')['requests'].items():require(g['requests'].get(k)==v,'parent shared request altered/refunded')
    return {'members':rows,'shared_charged_requests':len(g['requests']),'global_API_width':1,'new_API_requests':0,'new_solves':0,'new_compute_verification':False,'manifest':str(manifest)}


def activate(parent):
    inspect();parent_audit(parent,accounting=True)
    require(read(Path(parent)/'plans/first-eoh-501-502/Closed.json')['manifest_sha256']==sha(Path(parent)/read(PIN)['parent_plan']),'parent must be safely closed with its original close command')
    path=PLAN/'Shared.json';m=shared.load(path);lease=Path(m['account_gate'])/'generation.lock'
    require(not lease.exists(),'account generation lease exists; never delete or override it')
    require(not (PLAN/'Activation.json').exists(),'activation already reserved; inspect rather than retry')
    require(time.time()<m['account_exclusion']['valid_until'],'original exclusion expired; no renewal')
    registry=Path(m['account_gate'])/'continuations'/sha(Path(parent)/read(PIN)['parent_plan'])
    require(not registry.exists(),'parent already reserved for continuation; never import twice')
    identity={'protocol':'SHARED:'+sha(path),'batch':str(path),'version':shared.VERSION}
    claim(registry,{'state':'continuation_reserved','parent_manifest_sha256':sha(Path(parent)/read(PIN)['parent_plan']),'new_manifest_sha256':sha(path),'new_manifest':str(path),'automatic_retry':False})
    claim(PLAN/'Activation.json',{'state':'reserved','identity':identity,'account_lease':str(lease)})
    claim(lease,identity)
    write(PLAN/'Activation.json',{'state':'active','identity':identity,'account_lease':str(lease),'inherited_requests':20})
    return {'activated':True,'inherited_requests':20,'API_requests':0,'actual_solves':0,'automatic_submission':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['prepare','check-only','activate']);ap.add_argument('--parent-root',type=Path,default=Path(read(PIN)['parent_root']));a=ap.parse_args()
    result=prepare(a.parent_root) if a.action=='prepare' else inspect() if a.action=='check-only' else activate(a.parent_root)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
