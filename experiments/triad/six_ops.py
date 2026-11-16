#!/usr/bin/env python3
"""Six-group operator navigation; existing executors, admission, assets and Slurm only."""
import argparse
import copy
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from experiments.triad import configuration,runtime,parallel,shared_admission as shared,assets
from experiments.triad.concurrency_probe import claim
CONFIGS=ROOT/'configurations/six-groups-20261116'
R11=Path('/public2/home/qiuqian/hdl-deploy/triad-fjsp-stop-recovery-20261116-r11')
R11_PLAN=R11/'plans/stop-recovery-501-502/Shared.json'
PAIRS={'fjsp503':[('fjsp-u',503),('fjsp-eoh',503)],
       **{p+str(s):[(p+'-u',s),(p+'-eoh',s)] for p in ('tsp','obp') for s in (501,502,503)}}
TERMINAL={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}


def need(ok,message):
    if not ok:raise PermissionError(message)


def invoke(script,args,root=ROOT):
    p=subprocess.run([sys.executable,'-s','-B',str(root/'experiments/triad'/script),*map(str,args)],check=True,capture_output=True,text=True)
    return json.loads(p.stdout)


def manifest(name):
    need(name in PAIRS,'select one documented batch')
    return ROOT/'plans'/('six-'+name)/'Shared.json'


def config_path(group):
    bound=ROOT/'preparations/operations/configs'/(group+'.json')
    return bound if bound.exists() else CONFIGS/(group+'.json')


def config(group):
    return configuration.load(config_path(group))


def save_bound(group,c):
    cp=ROOT/'preparations/operations/configs'/(group+'.json')
    # Generated bindings live outside immutable source templates, before planning.
    for k in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results'):
        if c.get(k):c[k]=os.path.relpath(c[k],cp.parent)
    if isinstance(c.get('state_delivery'),dict):c['state_delivery']['file']=os.path.relpath(c['state_delivery']['file'],cp.parent)
    write(cp,c)
    return cp


def check_assets(c):
    missing=configuration.gaps(c)
    missing=[x for x in missing if x!='account_exclusion']
    for key in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results'):
        if c.get(key) and not Path(c[key]).is_file():missing.append('asset:'+key)
    if c['problem']=='tsp' and not c['reference_file']:missing.append('asset:D06_LKH_reference')
    if c['problem']=='obp' and c['method']=='u' and not c['h_file']:missing.append('asset:OBP_H401')
    if not missing:runtime.problems.load_inputs(c)
    return sorted(set(missing))


def inventory():
    rows=[]
    for group in configuration.GROUPS:
        c=config(group)
        for seed in (501,502,503):
            known=group=='fjsp-u' and seed in (501,502)
            running=group=='fjsp-eoh' and seed in (501,502)
            batch='fjsp503' if group.startswith('fjsp') else c['problem']+str(seed)
            run_id='six-'+batch+'-'+group+'-seed-'+str(seed)
            row={'中文名称':{'fjsp':'FJSP','tsp':'TSP','obp':'在线装箱'}[c['problem']]+('双层方法' if c['method']=='u' else '单规则EoH'),
                'group':group,'seed':seed,'state':'completed_read_only' if known else 'running_last_receipt_not_live_query' if running else 'not_started',
                'job_id':({501:'622861',502:'622862'}.get(seed) if running else '617156' if known and seed==502 else None),
                'config':str(config_path(group)),'run_id':run_id if not(known or running) else None,
                'run_dir':str(ROOT/'runs'/('six-'+batch)/run_id) if not(known or running) else 'original source; never initialize here',
                'budget':configuration.budget(c),'pending':[] if known or running else check_assets(c),
                'next_command':'original R11 status/finish' if running else 'do not rerun' if known else f'python -s -B experiments/triad/six_ops.py prepare --batch {batch} --confirm-exclusive-account --exclusive-hours 72'}
            rows.append(row)
    return rows


def check_only():
    rows=inventory()
    return {'check_only_passed':True,'runs':rows,'all_runs_ready':all(not r['pending'] for r in rows),
        'API_requests':0,'actual_solves':0,'credential_values_read':0,'Slurm_submitted':False,
        'unknown_protocol_is_environment_error':False,'API_width':1,'max_active_searches':2,
        'FJSP_EoH_policy':config('fjsp-eoh')['initialization_policy'],
        'TSP_decisions':read(ROOT/'preparations/operations/TSP-adoption.json') if (ROOT/'preparations/operations/TSP-adoption.json').exists() else read(CONFIGS/'TSP-decisions.pending.json')}


def prepare(name,hours,confirmed):
    p=manifest(name)
    need(hours is not None and confirmed,'fresh all-device agreement required for NEW batch; no auto renewal')
    rows=[]
    for group,seed in PAIRS[name]:
        c=config(group);missing=check_assets(c)
        need(not missing,'PROTOCOL_OR_ASSET_PENDING '+group+': '+', '.join(missing))
        rows.append({'group':group,'seed':seed,'config':str(config_path(group))})
    spec=ROOT/'plans'/('six-'+name+'.spec.json')
    need(not p.parent.exists() and not spec.exists(),'plan exists; inspect/resume its original identity, never recreate')
    gate=config(rows[0]['group'])['account_gate']
    write(spec,{'batch_id':'six-'+name,'mode':'real','min_request_interval_seconds':1,'queue_wait_seconds':600,'account_gate':gate,'members':rows})
    return parallel.plan(spec,p.parent,hours,confirmed)


def scheduler(rows):
    q=subprocess.run(['squeue','-h','-u','qiuqian','-o','%i|%T'],check=True,text=True,capture_output=True,timeout=30).stdout
    out=[]
    for row in rows:
        d=Path(row['run_dir']);r=read(d/'latest-submission.json');j=r.get('job_id','')
        need(r.get('state')=='submitted' and j.isdigit(),'unknown submission; retain claims, never resend')
        need(not any(x.split('|')[0].strip()==j for x in q.splitlines()),'job still queued/running; wait')
        raw=subprocess.run(['sacct','-n','-P','-j',j,'--format=JobIDRaw,State,ExitCode,NodeList'],check=True,text=True,capture_output=True,timeout=30).stdout
        exact=[x.split('|') for x in raw.splitlines() if x.split('|')[0]==j]
        need(len(exact)==1 and exact[0][1].split()[0] in TERMINAL,'exact terminal accounting missing; stop')
        out.append({'job_id':j,'state':exact[0][1],'exit_code':exact[0][2],'node':exact[0][3]})
    return out


def finish_check(path,require_complete=True):
    m=read(path);account=scheduler(m['members']);result=[]
    for row in m['members']:
        d=Path(row['run_dir']);s=read(d/'checkpoint.json')
        need(not any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json')),'writer/STOP retained; preserve diagnosis')
        need(s['phase'] in ('completed','paused','initialization_incomplete','expired'),'unsettled run')
        evo=s.get('generation_requests',s.get('eoh',{}).get('operator_cursor'))
        if require_complete:need(s['phase']=='completed' and evo==1000,'not a full1000 completion; do not close as success')
        result.append({'seed':row['seed'],'phase':s['phase'],'evolution_attempts':evo,'checkpoint_sha256':sha(d/'checkpoint.json')})
    return m,{'runs':result,'scheduler':account,'API_requests':0,'actual_solves':0}


def batch_status(name):
    p=manifest(name);v=parallel.inspect(p)
    v['scheduler_note']='Slurm terminal does not mean1000 evolution complete'
    return v


def continue_batch(name,approved,allow_api,allow_solves,send,prefix=False):
    p=manifest(name);m=shared.load(p)
    need(send and allow_api and allow_solves and approved==m['total_request_cap'],'explicit submit/API/solves/original aggregate budget required')
    if prefix:
        bounds={r['run_id']:(2 if r['group']=='fjsp-u' else 1) for r in m['members']}
        solves=sum(2*bounds[r['run_id']]*read(r['config'])['instance_count'] for r in m['members'])
        return parallel.submit(p,'run',True,approved,True,True,bounds,solves)
    finish_check(p,False)
    info=parallel.inspect(p)
    selected=[i for i,r in enumerate(info['members']) if r['phase']=='paused']
    need(selected and all(r['phase'] in ('paused','completed') for r in info['members']),'only settled paused runs may continue; no refill/reinitialize')
    if len(selected)==2:return parallel.submit(p,'resume',True,approved,True,True)
    return parallel.submit(p,'resume',True,approved,True,True,member=selected[0])


def close(name,confirmed):
    p=manifest(name);m,v=finish_check(p)
    need(confirmed,'retrieve and verify originals first; explicitly --confirm-retrieved')
    result=invoke('parallel.py',['close','--manifest',p])
    write(p.parent/'Finished.json',{**v,'closed':result,'at':time.time()})
    return result


def r11(action,confirmed=False):
    m,v=finish_check(R11_PLAN,action!='r11-status')
    if action=='r11-status':return v
    if action=='r11-export':
        for row in m['members']:
            invoke('entry.py',['export','--config',row['config'],'--run-dir',row['run_dir'],'--shared-manifest',R11_PLAN],R11)
        return {**v,'original_frozen_export_completed':True,'next':'Mac six_mac.py fetch-r11; then r11-close --confirm-retrieved'}
    need(confirmed,'fetch and verify R11 results first; require --confirm-retrieved')
    return invoke('parallel.py',['close','--manifest',R11_PLAN],R11)


def settle_known(name,acknowledged):
    """Explicit safe transition for NEW-release shared gates, never phase/journal edits."""
    need(acknowledged,'explicit charged-failure acknowledgment required')
    p=manifest(name);m=shared.load(p);account=scheduler(m['members'])
    a=shared.Admission({'manifest':str(p),'sha256':sha(p),'run_id':m['members'][0]['run_id']})
    a.verify();g=p.parent/'gate'
    need((g/'STOP.json').exists() and not any((g/n).exists() for n in ('metrics.lock','send-turn.lock')),'STOP required, unknown writer/send turn cannot be settled')
    original=read(g/'ledger.json');known={};attempts={};snapshots={};total=0
    for row in m['members']:
        d=Path(row['run_dir']);s=read(d/'checkpoint.json')
        protocol=read(d/'Protocol.json')
        need(s['identity']==sha(d/'Protocol.json'),'original protocol/checkpoint identity differs')
        for n,h in protocol.get('source_files',{}).items():
            need(not Path(n).is_absolute() and '..' not in Path(n).parts and sha(ROOT/n)==h,'frozen source differs; no hot repair')
        if protocol.get('version')==runtime.VERSION:
            need(protocol['config_sha256']==row['config_sha256'],'original native configuration binding differs')
        journal_path=d/'API_attempts.json'
        if not journal_path.exists():
            candidates=[f for f in (d/'operations').glob('*.json') if 'api_attempts' in read(f)]
            need(len(candidates)==1,'exact original U request journal required; no guessed rebind')
            journal_path=candidates[0]
        j=read(journal_path)
        need(s['phase'] in ('paused','completed') and not any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json')),'unsettled/blocked source; never rewrite phase')
        need(all(e.get('status')=='completed' for e in s.get('evaluations',{}).values()),'unsettled evaluation retained; never re-solve')
        need(not j.get('halt_reason'),'persistent client stop requires separate diagnosis; do not clear it')
        snapshots[str(d)]={n:sha(d/n) for n in ('checkpoint.json','Protocol.json','Run_clock.json',str(journal_path.relative_to(d)))}
        need(all(t.get('status') in ('completed','planned') for t in s['tasks'].values()),'unsettled task; no replay')
        total+=len(j['api_attempts'])
        for x in j['api_attempts'].values():
            uid=digest({'member':row['run_id'],'key':x['id']})
            need(x['number']==1 and x['status'] in ('completed','failed'),'unknown attempt or retry')
            need(uid not in attempts,'duplicate original attempt identity')
            attempts[uid]={'member':row['run_id'],'key':x['id'],'attempt':x}
            if x['status']=='failed':
                meta=x.get('metadata',{});sent=meta.get('send_status')
                no_send=not x.get('send_confirmed') and sent=='not_sent' and meta.get('failure_stage')=='shared_admission' and x.get('finished_at') is not None
                http=x.get('send_confirmed') and sent=='confirmed' and meta.get('failure_stage')=='http_receive' and meta.get('http_status') in (429,500,502,503,504,522,524) and x.get('finished_at') is not None
                need(no_send or http,'truly unknown/network/persistent error retained; no automatic resolution')
                known[uid]={'member':row['run_id'],'key':x['id'],'classification':'confirmed_not_sent' if no_send else 'confirmed_HTTP'+str(meta['http_status'])}
    need(known and set(original['active']).issubset(known),'unexplained active permit; retain')
    need(set(original['requests']).issubset(attempts),'orphan shared request; retain for diagnosis')
    missing=set(attempts)-set(original['requests'])
    need(all(uid in known and known[uid]['classification']=='confirmed_not_sent' for uid in missing),
         'only journal-only confirmed not_sent charges can be reconciled; unknown/physical send retained')
    for uid,r in original['requests'].items():
        need((r['member'],r['key'])==(attempts[uid]['member'],attempts[uid]['key']),'shared/journal identity differs')
        need(uid in known or r['state'] in ('completed','reconciled_failed'),'unknown shared settlement retained')
    need(total<=m['total_request_cap'] and all(sum(x['member']==r['run_id'] for x in attempts.values())<=r['request_cap'] for r in m['members']),
         'original per-member/aggregate budget exceeded')
    audit=p.parent/'known-failures'/str(time.time_ns())
    audit.mkdir(parents=True)
    write(audit/'Before.json',original);write(audit/'Audit.json',{'known':known,'journal_only_confirmed_not_sent':sorted(missing),'scheduler':account,'sources':snapshots,'charged':total,'refunds':0})
    with a.transaction() as s:
        need(s==original,'concurrent ledger change; STOP retained')
        for uid in known:
            if uid in missing:
                s['requests'][uid]={'member':known[uid]['member'],'key':known[uid]['key'],
                    'ticket':s['next_ticket'],'state':'reconciled_failed','send_state':'not_sent',
                    'reserved_at':attempts[uid]['attempt'].get('started_at'),
                    'journal_only_charge_preserved':True}
                s['next_ticket']+=1
            s['requests'][uid].update(state='reconciled_failed',reconciliation=str(audit/'Audit.json'))
            s['active'].pop(uid,None);a.event(s,'reconciled_terminal',uid=uid,member=known[uid]['member'])
        need(all(r['state'] in ('completed','reconciled_failed') for r in s['requests'].values()),'waiting/unknown request retained')
        s['jobs']={};a.event(s,'manual_known_failure_settlement',charged_retained=total)
    for d,files in snapshots.items():need(all(sha(Path(d)/n)==h for n,h in files.items()),'original identity/RNG/budget changed; stop')
    os.replace(g/'STOP.json',audit/'Original-STOP.json')
    return {'settled_known_failures':len(known),'journal_only_not_sent_preserved':len(missing),'charged_retained':total,'refunds':0,'phase_or_rng_writes':0,'API_requests':0,'solves':0,'next':'manual continue; no failed slot replay'}


def bind_asset(problem,path):
    path=Path(path).resolve();need(path.is_relative_to(ROOT/'preparations') and path.is_file(),'asset must be inside release preparations/')
    for method in ('u','eoh'):
        need(not any((ROOT/'plans'/('six-'+problem+str(s))).exists() for s in (501,502,503)),'bind BEFORE any plan; original config immutable')
        c=config(problem+'-'+method)
        if problem=='tsp':
            ref=read(path);need(ref.get('kind')=='fixed-LKH-reference-v1' and len(ref['instances'])==20,'complete20 LKH reference required')
            c['reference_file']=str(path)
        elif method=='u':
            h=read(path);need(h.get('problem')=='obp' and not h.get('engineering_only') and len(h['members'])==10,'real frozen10 OBP H required')
            c['h_file']=str(path)
        save_bound(problem+'-'+method,c)
    return {'bound':str(path),'sha256':sha(path),'API_requests':0,'solves':0}


def adopt_tsp(values):
    need(values is not None and len(values)==6,'explicit U_N U_INIT EOH_N EOH_INIT +policy codes expected')
    un,ui,en,ei,up,ep=values
    policies={1:'bounded_initialization_until_population',2:'native_N_finite_or_fail',3:'native_EoH'}
    need(up==1 and ep in (2,3) and un>=2 and en>=2 and ui>=un and ei>=en,'invalid population/init/policy choices')
    for method,n,init,policy in [('u',un,ui,up),('eoh',en,ei,ep)]:
        need(not any((ROOT/'plans'/('six-tsp'+str(s))).exists() for s in (501,502,503)),'no research edits after planning')
        c=config('tsp-'+method)
        c.update(population_size=n,initialization_request_cap=init,api_attempt_cap=init+1000,initialization_policy=policies[policy],freeze_status='frozen',budget_basis='operator explicitly adopted TSP parameters via six_ops; equal1000 evolution, init/H separate')
        save_bound('tsp-'+method,c)
    write(ROOT/'preparations/operations/TSP-adoption.json',{'at':time.time(),'explicit_values':values,'API_execution_authorized':False})
    return {'TSP_parameters_adopted':True,'API_requests':0,'solves':0}


def h_prepare(hours,confirmed):
    need(confirmed and hours is not None and 48<=hours<=168,'fresh all-device agreement48..168h required')
    c=config('obp-u');folder=ROOT/'preparations/operations/obp-H401';cp=folder/'config.json'
    need(not folder.exists(),'original H plan retained; use status/resume')
    c.update(search_seed=401,account_exclusion={'scope':'all_devices_sharing_account','valid_until':time.time()+hours*3600,'confirmation':'operator confirms only OBP H401 will request on all devices'})
    write(cp,c)
    return invoke('entry.py',['check-only','--kind','h-build','--config',cp])


def summarize():
    rows=inventory()
    for r in rows:
        d=Path(r['run_dir'])
        if (d/'exports/summary.json').exists():r.update(read(d/'exports/summary.json'))
    groups=[]
    import statistics
    for g in configuration.GROUPS:
        members=[r for r in rows if r['group']==g]
        values=[r['best_J'] for r in members if r.get('phase')=='completed' and r.get('evolution_attempts')==1000 and r.get('best_J') is not None]
        groups.append({'group':g,'declared_seeds':3,'complete_observed':len(values),'mean_J':statistics.mean(values) if values else None,'sample_std_J':statistics.stdev(values) if len(values)>1 else None,'failures_and_pending':[{'seed':r['seed'],'state':r.get('phase',r['state'])} for r in members if not(r.get('phase')=='completed' and r.get('evolution_attempts')==1000)]})
    out=ROOT/'reports/six-groups-summary';write(out/'Summary.json',{'all18':rows,'groups':groups,'missing_existing_evidence_is_not_zero':True,'actual_currency_cost':None})
    return {'summary':str(out/'Summary.json'),'all18_retained':True,'API_requests':0,'solves':0}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['check-only','prepare','activate','prefix-submit','certify','status','continue','pause','close','settle-known','r11-status','r11-export','r11-close','bind-tsp','bind-obp','adopt-tsp','obp-h-prepare','summary'])
    ap.add_argument('--batch',choices=tuple(PAIRS));ap.add_argument('--exclusive-hours',type=float);ap.add_argument('--confirm-exclusive-account',action='store_true');ap.add_argument('--confirm-retrieved',action='store_true')
    ap.add_argument('--submit',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-requests',type=int);ap.add_argument('--acknowledge-charged-failures',action='store_true');ap.add_argument('--asset',type=Path);ap.add_argument('--values',nargs=6,type=int)
    a=ap.parse_args()
    if a.action=='check-only':v=check_only()
    elif a.action=='prepare':v=prepare(a.batch,a.exclusive_hours,a.confirm_exclusive_account)
    elif a.action=='activate':
        need(a.confirm_exclusive_account,'explicit all-device agreement required');shared.activate(manifest(a.batch));v={'activated':True,'API_requests':0,'solves':0}
    elif a.action in ('prefix-submit','continue'):v=continue_batch(a.batch,a.approve_requests,a.allow_api,a.allow_solves,a.submit,a.action=='prefix-submit')
    elif a.action=='status':v=batch_status(a.batch)
    elif a.action=='certify':v=parallel.certify(manifest(a.batch))
    elif a.action=='pause':v=invoke('parallel.py',['pause','--manifest',manifest(a.batch)])
    elif a.action=='close':v=close(a.batch,a.confirm_retrieved)
    elif a.action.startswith('r11-'):v=r11(a.action,a.confirm_retrieved)
    elif a.action=='settle-known':v=settle_known(a.batch,a.acknowledge_charged_failures)
    elif a.action.startswith('bind-'):v=bind_asset('tsp' if a.action=='bind-tsp' else 'obp',a.asset)
    elif a.action=='adopt-tsp':v=adopt_tsp(a.values)
    elif a.action=='obp-h-prepare':v=h_prepare(a.exclusive_hours,a.confirm_exclusive_account)
    else:v=summarize()
    print(json.dumps(v,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False,'instruction':'stop and save this output; never delete locks/STOP or recreate budget'},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(2)
