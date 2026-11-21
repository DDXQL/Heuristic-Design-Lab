#!/usr/bin/env python3
"""Two independent sbatch jobs; immutable identities, budgets and manual actions."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from experiments.triad import configuration,runtime,slurm,shared_admission as shared
from experiments.triad.concurrency_probe import claim,stop


def plan(spec,folder,hours=None,confirmed=False):
    spec=Path(spec).resolve();folder=Path(folder).resolve();doc=read(spec)
    if not folder.is_relative_to(ROOT/'plans') or not doc['batch_id'] or any(v not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for v in doc['batch_id']):raise ValueError('safe new batch under this release plans/ required')
    if folder.exists():raise FileExistsError('new plan directory required; never replace a submitted plan')
    policy=doc.get('candidate_policy')
    independent=shared.independent(doc)
    if len(doc['members']) not in ((1,2,3) if independent else (1,2) if policy else (2,)):raise ValueError('select the supported number of independent runs')
    if not independent and doc['mode']=='real' and any(v['group']=='fjsp-u' and v['seed'] in (501,502) for v in doc['members']):raise PermissionError('completed FJSP U501/U502 are read-only, never scheduled')
    exclusion=None
    if hours is not None and not independent:
        allowed=doc['window_seconds']/3600<hours<=168 if policy else 48<=hours<=168
        if not confirmed or not allowed:raise PermissionError('explicit all-device exclusion covering the authorized campaign required')
        exclusion={'scope':'all_devices_sharing_account','valid_until':time.time()+hours*3600,'confirmation':'operator confirms all other devices, generators and queued jobs stopped; only these two admitted members may generate'}
    rows=[];manifest=folder/'Shared.json';run_root=ROOT/'runs'/doc['batch_id']
    for index,item in enumerate(doc['members']):
        c=configuration.load((spec.parent/item['config']).resolve(),engineering=doc['mode']=='mock')
        if item['group']!=c['group'] or item['seed'] not in c['search_seeds']:raise ValueError('seed/group outside declaration')
        run_id=doc['batch_id']+'-'+c['group']+'-seed-'+str(item['seed']);dest=folder/'configs'/(run_id+'.json')
        c.update(search_seed=item['seed'],account_gate=str(folder/'run-gates'/run_id),account_exclusion=exclusion,shared_manifest=str(manifest))
        if independent:c['resources']['independent_batch']=True
        if c['mode']!=doc['mode']:raise ValueError('Mock and real cannot share an admission batch')
        if policy:
            from .candidate_policy import validate
            validate(policy,c['evolution_request_cap'],real=c['mode']=='real')
            if c['group']=='fjsp-u' and not independent:raise PermissionError('FJSP U response counting requires an independent new batch')
            c.update(candidate_policy=policy,api_attempt_cap=c['initialization_request_cap']+policy['evolution_attempt_cap'],
                     per_candidate_attempt_cap=policy['per_slot_attempt_cap'],window_seconds=doc['window_seconds'])
            drain=configuration.candidate_drain(c,doc['queue_wait_seconds'])
            c['resources'].update(segment_seconds=doc['segment_seconds'],request_queue_seconds=doc['queue_wait_seconds'],
                                  drain_seconds=max(drain,c['resources']['drain_seconds']))
            if min(c['window_seconds'],c['resources']['segment_seconds'])<=c['resources']['drain_seconds']:
                raise ValueError('requested window/walltime does not cover drain')
        if c['api_attempt_cap'] is None:raise PermissionError('explicit member cap required even for a pending plan')
        write(dest,c); rows.append({'group':c['group'],'seed':item['seed'],'index':index,'run_id':run_id,'run_dir':str(run_root/run_id),'config':str(dest),'config_sha256':sha(dest),'child_config_sha256':sha(dest),'request_cap':c['api_attempt_cap'],'pending':configuration.gaps(c)})
    m={'version':shared.VERSION,'batch_id':doc['batch_id'],'mode':doc['mode'],'max_active_searches':2,'global_API_width':1,'API2':'implemented bounded extension; requires API1 actual acceptance and separate manual phase authorization; not adopted',
       'min_request_interval_seconds':doc['min_request_interval_seconds'],'queue_wait_seconds':doc['queue_wait_seconds'],'require_initial_preflight':True,
       'account_gate':doc['account_gate'],'account_exclusion':exclusion,'total_request_cap':sum(r['request_cap'] for r in rows),'members':rows,'real_requests_authorized':False}
    if doc.get('runtime_policy') is not None:
        if doc['runtime_policy'] not in (shared.EXPLORE,shared.INDEPENDENT):raise ValueError('unknown new runtime policy')
        m['runtime_policy']=doc['runtime_policy']
    if independent:
        m.update(max_active_searches=3,global_API_width=doc['global_API_width'],requests_per_minute=doc.get('requests_per_minute'))
        m.pop('API2')
    if policy:m['candidate_policy']=policy
    cs=[read(r['config']) for r in rows]
    m['aggregate_resources']={k:sum(c['resources'][k] for c in cs) if all(c['resources'][k] is not None for c in cs) else None for k in ('cpus','memory_mib')}
    m['native_solve_cap']=sum(configuration.budget(c)['native_solve_cap_per_seed'] for c in cs) if doc['mode']=='real' else 0
    write(manifest,m);shared.load(manifest)
    write(folder/'Batch.json',{'version':'triad-shared-two-batch-plan-v1','campaign_id':doc['batch_id'],'rows':rows,'same_account_generation_tasks':len(rows),'shared_manifest':str(manifest)})
    return {'manifest':str(manifest),'members':rows,'total_original_request_cap':m['total_request_cap'],'CODE_READY':True,'RUN_READY':False,'API_requests':0,'actual_solves':0}


def mock_plan(folder):
    folder=Path(folder).resolve();source=ROOT/'experiments/triad/recommended.draft/fjsp-eoh.json'
    c=configuration.load(source);c.update(mode='mock',freeze_status='engineering_only',repeat_count=2,search_seeds=[502,503],population_size=2,initialization_request_cap=4,evolution_request_cap=8,api_attempt_cap=12,window_seconds=1800,protocol_receipt='ENGINEERING MOCK ONLY',budget_basis='SYNTHETIC; not research',account_gate=None,account_exclusion=None,credential_file=None)
    c['resources'].update(cpus=2,memory_mib=1024,segment_seconds=1800,drain_seconds=1260,partition='128C_02',account='wz',qos='normal')
    folder.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mock-input-',dir=folder.parent) as tmp:
        temp=Path(tmp);write(temp/'config.json',c);write(temp/'spec.json',{'batch_id':folder.name,'mode':'mock','min_request_interval_seconds':1,'queue_wait_seconds':360,'account_gate':str(folder/'engineering-account'),'members':[{'group':'fjsp-eoh','seed':seed,'config':str(temp/'config.json')} for seed in (502,503)]})
        return plan(temp/'spec.json',folder)


def inspect(path):
    path=Path(path).resolve();m=shared.load(path);rows=[]
    for row in m['members']:
        d=Path(row['run_dir']);c=configuration.load(row['config'],engineering=m['mode']=='mock')
        if sha(row['config'])!=row['config_sha256']:raise ValueError('member config changed')
        names={'fjsp':'FJSP','tsp':'TSP','obp':'在线装箱'}
        label=names[c['problem']]+('双层方法' if c['method']=='u' else '单规则EoH')+'，种子 '+str(row['seed'])
        try:
            with (d/'checkpoint.json').open() as handle:
                cp=json.load(handle)
                checkpoint_mtime=os.fstat(handle.fileno()).st_mtime
        except FileNotFoundError:
            cp={}
        except (OSError,ValueError) as error:
            if not shared.independent(m):raise
            rows.append({'run_id':row['run_id'],'phase':'unavailable','pause_reason':str(error),'group':row['group']})
            continue
        item={'中文名称':label,'run_id':row['run_id'],'seed':row['seed'],'group':row['group'],'phase':cp.get('phase','not_started'),'pending':configuration.gaps(c),'original_request_cap':row['request_cap'],'resources':c['resources'],'run_dir':str(d)}
        if cp:
            item['checkpoint_updated_at']=checkpoint_mtime
            item['used_logical_attempts']=cp.get('completed_tasks',cp.get('cursor'))
            item['initialization_requests']=cp.get('initialization_requests',cp.get('eoh',{}).get('initialization_requests'))
            item['evolution_requests']=cp.get('generation_requests',cp.get('eoh',{}).get('operator_cursor'))
            if m.get('candidate_policy'):
                item.update(successful_evolution_responses=cp.get('successful_evolution_responses',0),
                            successful_evolution_target=c['evolution_request_cap'],pause_reason=cp.get('pause_reason'))
            item['writer_lock']=any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json')) or bool(c.get('account_gate') and (Path(c['account_gate'])/'generation.lock').exists())
            progress=read(d/'Progress.json') if (d/'Progress.json').exists() else read(d/'exports/summary.json') if (d/'exports/summary.json').exists() else {}
            item['reported_metrics']={k:progress.get(k) for k in ('best_J','champion_id','valid_candidates','failures','duplicates','confirmed_sends','unknown_sends','physical_passes')}
            if m.get('candidate_policy'):
                item['reported_metrics'].update({k:progress.get(k) for k in
                    ('reservations_by_stage','physical_sends_confirmed','physical_sends_unknown','unresolved_wire_outcomes','retry_reservations','retry_physical_sends_confirmed',
                     'confirmed_sends_usage_unknown','known_tokens','api_failed_attempts')})
        item['submissions']=[read(f) for f in (d/'submissions').glob('shared-*.json')];rows.append(item)
    state=read(path.parent/'gate/ledger.json') if (path.parent/'gate/ledger.json').exists() else None
    width=shared.Admission({'manifest':str(path),'sha256':sha(path),'run_id':m['members'][0]['run_id']}).phase(state)[0] if state is not None else m['global_API_width']
    return {'members':rows,'effective_global_API_width':width,'total_original_request_cap':m['total_request_cap'],'shared':None if state is None else {'reserved':len(state['requests']),'peak_permits':state['peak'],'confirmed_send_to_settlement_peak':sent_peak(state),'active':state['active'],'active_searches':state['jobs'],'states':{k:sum(r['state']==k for r in state['requests'].values()) for k in ('waiting','admitted','sent','completed','reconciled_failed','failed_or_unknown')},'API_wait_seconds':sum(r.get('wait_seconds',0) for r in state['requests'].values()),'wire_seconds':sum(r.get('wire_seconds',0) for r in state['requests'].values())},'STOP':(path.parent/'gate/STOP.json').exists(),'RUN_READY':False,'API_requests_by_inspection':0,'actual_solves_by_inspection':0}


def sent_peak(state):
    active=set();peak=0
    for event in state['events']:
        if event['event']=='sent':active.add(event['uid']);peak=max(peak,len(active))
        elif event['event'] in ('settled','reconciled_terminal'):active.discard(event['uid'])
    return peak


def argv(row,action,path,prefix=None):
    c=configuration.load(row['config'],engineering=True)
    cmd=[sys.executable,'-s','-B',str(ROOT/'experiments/triad/entry.py'),action,'--config',row['config'],'--run-dir',row['run_dir'],'--shared-manifest',str(path)]
    if c['mode']=='mock':cmd+=['--engineering']
    elif action in ('prepare','run','resume'):cmd+=['--allow-api','--allow-solves','--approve-budget',str(row['request_cap'])]
    if prefix is not None:
        cp=read(Path(row['run_dir'])/'checkpoint.json') if (Path(row['run_dir'])/'checkpoint.json').exists() else {}
        used=cp.get('completed_tasks',cp.get('cursor',0));cap=0 if c['mode']=='mock' else 2*(prefix-used)*c['instance_count']
        cmd+=['--pause-after-attempts',str(prefix),'--approve-segment-solves',str(cap)]
    return cmd


def submit(path,action,send=False,approved=None,allow_api=False,allow_solves=False,prefix=None,solve_cap=None,member=None,*,members=None):
    path=Path(path).resolve();m=shared.load(path);commands=[];new_solves=0
    selected=( [m['members'][i] for i in members] if members is not None
               else m['members'] if member is None else [m['members'][member]])
    if not selected or len({r['index'] for r in selected})!=len(selected):
        raise ValueError('nonempty distinct selection required')
    pf=lambda r: prefix[r['index']] if isinstance(prefix,dict) else prefix
    if isinstance(prefix,dict) and set(prefix)!={r['index'] for r in selected}:raise ValueError('one explicit finite boundary for every selected member')
    for row in selected:
        c=configuration.load(row['config'],engineering=m['mode']=='mock')
        pending=configuration.gaps(c)
        if pending:raise PermissionError('PROTOCOL_PENDING '+row['run_id']+': '+', '.join(pending))
        if sha(row['config'])!=row['config_sha256']:raise ValueError('configuration changed')
        d=Path(row['run_dir']);cp=read(d/'checkpoint.json') if (d/'checkpoint.json').exists() else {}
        used=cp.get('completed_tasks',cp.get('cursor',0))
        bound=pf(row)
        if bound is not None and not used<bound<=row['request_cap']:raise ValueError('finite prefix must extend the original settled cursor')
        segment_cap=(0 if c['mode']=='mock' else 2*(bound-used)*c['instance_count']) if bound is not None else None
        new_solves+=segment_cap or 0
        # Reuse the existing resource and command builder; use the new thin shell.
        if m['mode']=='real' or m.get('candidate_policy'):
            if m.get('candidate_policy') and action=='resume':
                remaining=int(read(d/'Run_clock.json')['deadline']-time.time())
                if remaining<=c['resources']['drain_seconds']:raise PermissionError('remaining calendar cannot cover drain')
                wall=min(remaining,c['resources']['segment_seconds'])
            else:wall=None
            wall_override={'wall_seconds':wall} if wall is not None else {}
            python=sys.executable if m.get('candidate_policy') else '/public2/home/qiuqian/hdl-envs/portable-v2/bin/python'
            cmd=slurm.command(row,action,python,bound,segment_cap,**wall_override)
            cmd[-(8 if prefix is not None else 6)]=str(ROOT/'experiments/triad/parallel.sbatch')
            cmd+=(['',''] if prefix is None else [])+[str(path)]
            certificate=path.parent/'Acceptance.json'
            if certificate.exists() and not shared.exploration(m):
                accepted=read(certificate)
                if accepted.get('manifest_sha256')!=sha(path) or accepted.get('adapter_sha256')!=sha(shared.__file__):raise PermissionError('original bounded acceptance changed')
                cmd.insert(cmd.index(str(ROOT/'experiments/triad/parallel.sbatch')),'--nodelist='+accepted['validated_nodes'][row['index']])
        else:
            r=c['resources'];cmd=['sbatch','--parsable','--no-requeue','--nodes=1','--ntasks=1','--cpus-per-task='+str(r['cpus']),'--mem='+str(r['memory_mib'])+'M','--time=00:30:00','--partition='+r['partition'],'--account='+str(r['account'] or ''),'--qos='+str(r['qos'] or ''),'--chdir='+str(ROOT),'--job-name='+row['run_id'],'--output='+str(ROOT/'logs'/(row['run_id']+'-%j.out')),str(ROOT/'experiments/triad/parallel.sbatch'),action,row['config'],row['run_dir'],'/public2/home/qiuqian/hdl-envs/portable-v2/bin/python',str(row['request_cap']),str(bound) if bound is not None else '',str(segment_cap) if segment_cap is not None else '',str(path)]
        commands.append(cmd)
    if not send:return {'submitted':False,'commands':commands,'original_total_request_cap':m['total_request_cap'],'finite_segment_solve_cap':new_solves if prefix is not None else None}
    if m['mode']=='real' and (approved!=m['total_request_cap'] or not allow_api or not allow_solves):raise PermissionError('explicit original aggregate cap/API/solve approval required')
    if (path.parent/'gate/STOP.json').exists() or (path.parent/'Closed.json').exists():raise PermissionError('stopped/closed batch cannot submit')
    if prefix is not None and solve_cap!=new_solves:raise PermissionError('exact inclusive aggregate first+recheck solve cap required')
    if m['mode']=='real' and prefix is None and not shared.exploration(m):
        certificate=read(path.parent/'Acceptance.json')
        if certificate.get('kind')=='audited-R9-stop-recovery-topology':
            from experiments.triad.stop_recovery import verify_acceptance
            verify_acceptance(path,certificate,require_finite=True)
        elif certificate.get('kind')=='inherited_admission_not_new_compute_verification':
            from experiments.triad.native_continuation import verify_inherited_acceptance
            verify_inherited_acceptance(path,certificate)
        elif not certificate.get('real_dispatch_path_verified') or certificate.get('manifest_sha256')!=sha(path) or certificate.get('adapter_sha256')!=sha(shared.__file__):raise PermissionError('new-version bounded real dispatch acceptance required before full resume')
        if (path.parent/'API2.finite.json').exists() and not (path.parent/'API2.decision.json').exists():raise PermissionError('API2 finite phase must be explicitly adopted or returned to API1 before full resume')
    shared.Admission({**{'manifest':str(path),'sha256':sha(path)},'run_id':m['members'][0]['run_id']}).verify()
    # All durable submission claims exist before the first sbatch. Unknowns stop
    # the batch, retain both claims, and are never retried or re-reserved.
    run_claims=[]
    for row in m['members']:
        for f in (Path(row['run_dir'])/'submissions').glob('shared-*.json'):
            if read(f).get('state')!='submitted':raise PermissionError('unknown submission anywhere in batch; no resend')
    for row in selected:
        d=Path(row['run_dir'])
        for f in (d/'submissions').glob('shared-*.json'):
            old=read(f)
            if old.get('state')!='submitted':raise PermissionError('unknown submission retained; no resend')
            a=subprocess.run(['sacct','-n','-P','-j',old['job_id'],'--format=JobIDRaw,State'],text=True,capture_output=True,check=True)
            state=next((x.split('|')[1].split()[0] for x in a.stdout.splitlines() if x.split('|')[0]==old['job_id']),None)
            if state not in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}:raise PermissionError('previous segment active or accounting unknown')
        if not (d/'Protocol.json').exists():
            if action!='run':raise PermissionError('resume cannot initialize a new run')
            subprocess.run(argv(row,'prepare',path),check=True,capture_output=True,text=True)
        cp=read(d/'checkpoint.json')
        if cp['phase']!=('prepared' if action=='run' else 'paused') or any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json')):raise PermissionError('run needs prepared; resume needs safely paused original state')
        claim_path=d/'submissions'/('shared-'+action+'-'+sha(d/'checkpoint.json')+'.json')
        run_claims.append(claim_path)
    for row,p,cmd in zip(selected,run_claims,commands):claim(p,{'state':'submission_reserved','run_id':row['run_id'],'command':cmd,'original_cap':row['request_cap'],'finite_settled_prefix':pf(row),'automatic_retry':False})
    (ROOT/'logs').mkdir(exist_ok=True);receipts=[]
    allocation={'identity':'allocation-'+str(time.time_ns()),'manifest_sha256':sha(path),'state':'reserved','jobs':{},'members':[r['run_id'] for r in selected]}
    if shared.exploration(m):
        claim(path.parent/'allocations'/(allocation['identity']+'.json'),allocation)
        shared.durable(path.parent/'Current_allocation.json',allocation)
    try:
        for row,p,cmd in zip(selected,run_claims,commands):
            result=subprocess.run(cmd,check=True,text=True,capture_output=True);job=result.stdout.strip().split(';')[0]
            if not job.isdigit():raise RuntimeError('unknown sbatch receipt; inspect, do not resubmit')
            record={**read(p),'state':'submitted','job_id':job};write(p,record);write(Path(row['run_dir'])/'latest-submission.json',record);receipts.append(record)
        if shared.exploration(m):
            allocation.update(state='submitted',jobs={r['run_id']:r['job_id'] for r in receipts})
            shared.durable(path.parent/'allocations'/(allocation['identity']+'.json'),allocation)
            shared.durable(path.parent/'Current_allocation.json',allocation)
    except BaseException:
        if not shared.independent(m):stop(path.parent/'gate','unknown/failed submission; all claims retained')
        raise
    width=shared.Admission({'manifest':str(path),'sha256':sha(path),'run_id':m['members'][0]['run_id']}).phase(None)[0]
    return {'submitted':True,'receipts':receipts,'original_aggregate_cap':m['total_request_cap'],'finite_new_solve_cap':new_solves if prefix is not None else None,'global_API_width':width,'max_active_searches':m['max_active_searches']}


def certify(path,phase=1):
    path=Path(path).resolve();m=shared.load(path);info=inspect(path);s=read(path.parent/'gate/ledger.json');jobs=[];hosts=[];nodes=[];actual_solves=0
    if info['STOP'] or s['active'] or s['jobs']:raise PermissionError('unknown/active evidence retained')
    if phase not in (1,2):raise ValueError('bounded acceptance phase1/API1 or phase2/API2 only')
    if phase==2 and not (path.parent/'API2.finite.json').exists():raise PermissionError('explicit finite API2 authorization required')
    prefixes=[read(Path(r['run_dir'])/'latest-submission.json').get('finite_settled_prefix') for r in m['members']]
    if any(type(v) is not int or v<1 for v in prefixes):raise PermissionError('explicit finite original-prefix submission receipts required')
    expected_sends=sum(prefixes)
    for i,row in enumerate(m['members']):
        d=Path(row['run_dir']);cp=read(d/'checkpoint.json');r=read(d/'latest-submission.json');job=r.get('job_id','')
        expected_prefix=prefixes[i]
        if cp['phase']!='paused' or cp.get('completed_tasks',cp.get('cursor'))!=expected_prefix or r['state']!='submitted' or not job.isdigit():raise PermissionError('two settled bounded Slurm prefixes required (EoH1, U whole init wave2)')
        account=subprocess.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode,NodeList'],check=True,text=True,capture_output=True)
        actual=next((x.split('|') for x in account.stdout.splitlines() if x.split('|')[0]==job),None)
        if not actual or actual[:3]!=[job,'COMPLETED','0:0'] or not actual[3] or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.' for ch in actual[3]):raise PermissionError('terminal successful single-node Slurm receipt required')
        nodes.append(actual[3])
        jobs.append(job);ready=read(path.parent/'preflight'/f'ready-{i}.json');hosts.append(ready['host'])
        expected_job=job if phase==1 else read(path.parent/'Acceptance.json')['two_actual_Slurm_jobs'][i]
        if ready['job_id']!=expected_job or not read(path.parent/'preflight'/f'fs-pass-{i}.json')['passed']:raise PermissionError('actual job filesystem preflight missing')
        if phase==2 and nodes[i]!=read(path.parent/'Acceptance.json')['validated_nodes'][i]:raise PermissionError('API2 must retain accepted node topology')
        if m['mode']=='real':
            tasks=list(cp['tasks'].values())
            if len(tasks)!=expected_prefix or any(not t.get('valid') or t.get('failure') for t in tasks):raise PermissionError('finite real prefix must be valid/unique and completely evaluated; do not refill failures')
            if c:=read(d/'Protocol.json'):
                if c.get('run_kind')=='eoh' and c.get('H_prompt_contract')!=runtime.h_contract.identity(c['config']['problem'],c['config'].get('obp_h_abi'),runtime.problems.obp_contract(c['config']) if c['config']['problem']=='obp' else None):raise PermissionError('actual repaired H prompt identity required')
            member_solves=0
            for receipt in cp['evaluations'].values():
                result_path=d/receipt['path']
                if sha(result_path)!=receipt['sha256']:raise ValueError('finite evaluation receipt changed')
                result=read(result_path)
                if not result['valid'] or result.get('mock') or len(result['instances'])!=len(c['instances']):raise PermissionError('complete real evaluation required')
                for result_row in result['instances']:
                    if result_row.get('captured_solves')!=2 or result_row['semantic_sha256']!=result_row['recheck_semantic_sha256']:raise PermissionError('exact independent first/recheck receipts required')
                    member_solves+=2
            if member_solves!=2*expected_prefix*len(c['instances']):raise PermissionError('bounded physical solve count differs; no hidden repeat or cached duplicate acceptance')
            actual_solves+=member_solves
    if len(set(jobs))!=2 or len(s['requests'])!=expected_sends or s['peak']!=phase or sent_peak(s)!=phase or any(r['state']!='completed' for r in s['requests'].values()):raise PermissionError('exact bounded successful prefix sends and actual sent-to-settled overlap required')
    value={'manifest_sha256':sha(path),'adapter_sha256':sha(shared.__file__),'phase':phase,'two_actual_Slurm_jobs':jobs,'hosts':hosts,'validated_nodes':nodes,'scope':'cross_node' if len(set(nodes))==2 else 'same_node','real_dispatch_path_verified':m['mode']=='real','compute_node_mock_verified':m['mode']=='mock','API_requests':expected_sends if m['mode']=='real' else 0,'solves_upper_bound':sum(2*n*configuration.load(r['config'],engineering=True)['instance_count'] for n,r in zip(prefixes,m['members'])) if m['mode']=='real' else 0,'RUN_READY':False,'note':'finite specified topology only; API2 counts include API1 prefix; no provider maximum/RPM/TPM claim'}
    value['actual_solves_including_recheck']=actual_solves
    claim(path.parent/('Acceptance.json' if phase==1 else 'API2.Acceptance.json'),value);return value


def authorize_api2(path,additional,solves):
    path=Path(path).resolve();m=shared.load(path);proof=read(path.parent/'Acceptance.json');info=inspect(path);s=read(path.parent/'gate/ledger.json')
    if m['mode']!='real' or any(r['group']!='fjsp-eoh' for r in m['members']):raise PermissionError('first bounded API2 extension is only the already-admitted two FJSP EoH searches')
    if not proof['real_dispatch_path_verified'] or proof['manifest_sha256']!=sha(path) or proof['adapter_sha256']!=sha(shared.__file__):raise PermissionError('matching actual API1 acceptance required')
    if additional!=2 or solves!=84 or info['STOP'] or s['active'] or s['jobs'] or len(s['requests'])!=2 or any(r['state']!='completed' for r in s['requests'].values()) or any(r['phase']!='paused' or r['used_logical_attempts']!=1 or r['writer_lock'] for r in info['members']):raise PermissionError('two safely paused first attempts, no unknowns; exactly2 additional requests/84 inclusive solves required')
    value={'manifest_sha256':sha(path),'adapter_sha256':sha(shared.__file__),'before_reservations':2,'reservation_stop_at':4,'additional_requests':2,'additional_solves_upper':84,'width':2,'adopted_for_full_search':False,'automatic_retry':False}
    b={'manifest':str(path),'sha256':sha(path),'run_id':m['members'][0]['run_id']}
    with shared.Admission(b).transaction() as current:
        if current['active'] or current['jobs'] or len(current['requests'])!=2:raise PermissionError('phase changed during authorization')
        claim(path.parent/'API2.finite.json',value);current['API2_finite_sha256']=sha(path.parent/'API2.finite.json')
    return value


def decide_api2(path,width,approved):
    path=Path(path).resolve();m=shared.load(path);s=read(path.parent/'gate/ledger.json');info=inspect(path)
    if width not in (1,2) or approved!=m['total_request_cap'] or info['STOP'] or s['active'] or s['jobs'] or len(s['requests'])!=4 or any(r['state']!='completed' for r in s['requests'].values()):raise PermissionError('settled finite phase and explicit original aggregate approval required')
    certificate=path.parent/'API2.Acceptance.json'
    if width==2 and (not read(certificate)['real_dispatch_path_verified'] or read(certificate)['manifest_sha256']!=sha(path)):raise PermissionError('actual API2 acceptance required before adoption')
    value={'finite_sha256':sha(path.parent/'API2.finite.json'),'width':width,'acceptance_sha256':sha(certificate) if width==2 else None,'original_aggregate_cap':approved}
    b={'manifest':str(path),'sha256':sha(path),'run_id':m['members'][0]['run_id']}
    with shared.Admission(b).transaction() as current:
        if current['active'] or current['jobs'] or len(current['requests'])!=4:raise PermissionError('phase changed during decision')
        claim(path.parent/'API2.decision.json',value);current['API2_decision_sha256']=sha(path.parent/'API2.decision.json')
    return value


def close(path, *, accounting=None):
    m=shared.load(path)
    if shared.independent(m):
        from .time_continuation import TERMINAL
        receipts=[read(p) for row in m['members']
                  for p in (Path(row['run_dir'])/'submissions').glob('shared-*.json')]
        if not receipts or accounting is None or any(
            r.get('state')!='submitted' or accounting.get(r.get('job_id'),{}).get('state') not in TERMINAL
            for r in receipts):
            raise PermissionError('previous Slurm jobs must be terminal before releasing the batch owner')
    else:
        check_shared_close(path)
    lease=Path(m['account_gate'])/'generation.lock'
    if read(lease).get('protocol')!='SHARED:'+sha(path):raise PermissionError('not this batch lease')
    claim(path.parent/'Closed.json',{'at':time.time(),'manifest_sha256':sha(path)})
    lease.unlink()
    return {'closed':True,'resume_prohibited':True}


def check_shared_close(path):
    info=inspect(path);s=read(path.parent/'gate/ledger.json')
    if (info['STOP'] or any((path.parent/'gate'/p).exists() for p in ('metrics.lock','send-turn.lock'))
        or s['active'] or s['jobs'] or any(v['state'] not in ('completed','reconciled_failed') for v in s['requests'].values())
        or any(r['phase'] not in ('completed','paused','initialization_incomplete','expired') or r.get('writer_lock') for r in info['members'])):
        raise PermissionError('unsafe/unknown batch retained; no close')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['plan','mock-plan','check-only','activate','submit','resume','certify','status','pause','close','authorize-api2','decide-api2']);ap.add_argument('--spec',type=Path);ap.add_argument('--directory',type=Path);ap.add_argument('--manifest',type=Path);ap.add_argument('--exclusive-hours',type=float);ap.add_argument('--confirm-exclusive-account',action='store_true');ap.add_argument('--submit',action='store_true');ap.add_argument('--approve-requests',type=int);ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--settled-prefix',type=int);ap.add_argument('--approve-segment-solves',type=int);ap.add_argument('--member',type=int,choices=[0,1]);ap.add_argument('--phase',type=int,choices=[1,2],default=1);ap.add_argument('--additional-requests',type=int);ap.add_argument('--width',type=int,choices=[1,2]);a=ap.parse_args()
    if a.action=='plan':value=plan(a.spec,a.directory,a.exclusive_hours,a.confirm_exclusive_account)
    elif a.action=='mock-plan':value=mock_plan(a.directory)
    elif a.action in ('check-only','status'):value=inspect(a.manifest)
    elif a.action=='activate':
        if shared.load(a.manifest)['mode']=='real' and not a.confirm_exclusive_account:raise PermissionError('explicit all-other-generators-stopped confirmation required')
        shared.activate(a.manifest);value={'activated':True,'API_requests':0,'actual_solves':0}
    elif a.action in ('submit','resume'):value=submit(a.manifest,'resume' if a.action=='resume' else 'run',a.submit,a.approve_requests,a.allow_api,a.allow_solves,a.settled_prefix,a.approve_segment_solves,a.member)
    elif a.action=='certify':value=certify(a.manifest,a.phase)
    elif a.action=='authorize-api2':value=authorize_api2(a.manifest,a.additional_requests,a.approve_segment_solves)
    elif a.action=='decide-api2':value=decide_api2(a.manifest,a.width,a.approve_requests)
    elif a.action=='pause':
        m=shared.load(a.manifest);rows=m['members'] if a.member is None else [m['members'][a.member]]
        value={'pause_requested':[]}
        for row in rows:subprocess.run(argv(row,'pause',a.manifest),check=True);value['pause_requested'].append(row['run_id'])
    else:value=close(a.manifest)
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
