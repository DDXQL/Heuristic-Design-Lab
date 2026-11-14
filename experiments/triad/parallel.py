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
    if len(doc['members'])!=2:raise ValueError('exactly two selected independent runs required')
    if any(v['group']=='fjsp-u' and v['seed']==501 for v in doc['members']):raise PermissionError('U501 is registered read-only, never scheduled')
    exclusion=None
    if hours is not None:
        if not confirmed or not 48<=hours<=168:raise PermissionError('explicit all-device exclusion of 48..168 hours required')
        exclusion={'scope':'all_devices_sharing_account','valid_until':time.time()+hours*3600,'confirmation':'operator confirms all other devices, generators and queued jobs stopped; only these two admitted members may generate'}
    rows=[];manifest=folder/'Shared.json';run_root=ROOT/'runs'/doc['batch_id']
    for index,item in enumerate(doc['members']):
        c=configuration.load((spec.parent/item['config']).resolve(),engineering=doc['mode']=='mock')
        if item['group']!=c['group'] or item['seed'] not in c['search_seeds']:raise ValueError('seed/group outside declaration')
        run_id=doc['batch_id']+'-'+c['group']+'-seed-'+str(item['seed']);dest=folder/'configs'/(run_id+'.json')
        c.update(search_seed=item['seed'],account_gate=str(folder/'run-gates'/run_id),account_exclusion=exclusion,shared_manifest=str(manifest))
        if c['mode']!=doc['mode']:raise ValueError('Mock and real cannot share an admission batch')
        if c['api_attempt_cap'] is None:raise PermissionError('explicit member cap required even for a pending plan')
        write(dest,c); rows.append({'group':c['group'],'seed':item['seed'],'index':index,'run_id':run_id,'run_dir':str(run_root/run_id),'config':str(dest),'config_sha256':sha(dest),'child_config_sha256':sha(dest),'request_cap':c['api_attempt_cap'],'pending':configuration.gaps(c)})
    m={'version':shared.VERSION,'batch_id':doc['batch_id'],'mode':doc['mode'],'max_active_searches':2,'global_API_width':1,'API2':'pending explicit future validation; prohibited by this version',
       'min_request_interval_seconds':doc['min_request_interval_seconds'],'queue_wait_seconds':doc['queue_wait_seconds'],'require_initial_preflight':True,
       'account_gate':doc['account_gate'],'account_exclusion':exclusion,'total_request_cap':sum(r['request_cap'] for r in rows),'members':rows,'real_requests_authorized':False}
    cs=[read(r['config']) for r in rows]
    m['aggregate_resources']={k:sum(c['resources'][k] for c in cs) if all(c['resources'][k] is not None for c in cs) else None for k in ('cpus','memory_mib')}
    m['native_solve_cap']=sum(2*c['api_attempt_cap']*c['instance_count'] for c in cs) if doc['mode']=='real' else 0
    write(manifest,m);shared.load(manifest)
    write(folder/'Batch.json',{'version':'triad-shared-two-batch-plan-v1','campaign_id':doc['batch_id'],'rows':rows,'same_account_generation_tasks':2,'shared_manifest':str(manifest)})
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
        cp=read(d/'checkpoint.json') if (d/'checkpoint.json').exists() else {}
        item={'run_id':row['run_id'],'seed':row['seed'],'group':row['group'],'phase':cp.get('phase','not_started'),'pending':configuration.gaps(c),'original_request_cap':row['request_cap'],'resources':c['resources'],'run_dir':str(d)}
        if cp:
            item['used_logical_attempts']=cp.get('completed_tasks',cp.get('cursor'))
            item['initialization_requests']=cp.get('initialization_requests',cp.get('eoh',{}).get('initialization_requests'))
            item['evolution_requests']=cp.get('generation_requests',cp.get('eoh',{}).get('operator_cursor'))
            item['writer_lock']=any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json'))
            progress=read(d/'Progress.json') if (d/'Progress.json').exists() else read(d/'exports/summary.json') if (d/'exports/summary.json').exists() else {}
            item['reported_metrics']={k:progress.get(k) for k in ('best_J','champion_id','valid_candidates','failures','duplicates','confirmed_sends','unknown_sends','physical_passes')}
        item['submissions']=[read(f) for f in (d/'submissions').glob('shared-*.json')];rows.append(item)
    state=read(path.parent/'gate/ledger.json') if (path.parent/'gate/ledger.json').exists() else None
    return {'members':rows,'total_original_request_cap':m['total_request_cap'],'shared':None if state is None else {'reserved':len(state['requests']),'peak_permits':state['peak'],'active':state['active'],'active_searches':state['jobs'],'states':{k:sum(r['state']==k for r in state['requests'].values()) for k in ('waiting','admitted','sent','completed','failed_or_unknown')},'API_wait_seconds':sum(r.get('wait_seconds',0) for r in state['requests'].values()),'wire_seconds':sum(r.get('wire_seconds',0) for r in state['requests'].values())},'STOP':(path.parent/'gate/STOP.json').exists(),'RUN_READY':False,'API_requests_by_inspection':0,'actual_solves_by_inspection':0}


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


def submit(path,action,send=False,approved=None,allow_api=False,allow_solves=False,prefix=None,solve_cap=None,member=None):
    path=Path(path).resolve();m=shared.load(path);commands=[];new_solves=0
    selected=m['members'] if member is None else [m['members'][member]]
    for row in selected:
        c=configuration.load(row['config'],engineering=m['mode']=='mock')
        pending=configuration.gaps(c)
        if pending:raise PermissionError('PROTOCOL_PENDING '+row['run_id']+': '+', '.join(pending))
        if sha(row['config'])!=row['config_sha256']:raise ValueError('configuration changed')
        d=Path(row['run_dir']);cp=read(d/'checkpoint.json') if (d/'checkpoint.json').exists() else {}
        used=cp.get('completed_tasks',cp.get('cursor',0))
        if prefix is not None and not used<prefix<=row['request_cap']:raise ValueError('finite prefix must extend the original settled cursor')
        segment_cap=(0 if c['mode']=='mock' else 2*(prefix-used)*c['instance_count']) if prefix is not None else None
        new_solves+=segment_cap or 0
        # Reuse the existing resource and command builder; use the new thin shell.
        if m['mode']=='real':
            cmd=slurm.command(row,action,'/public2/home/qiuqian/hdl-envs/portable-v2/bin/python',prefix,segment_cap)
            cmd[-(8 if prefix is not None else 6)]=str(ROOT/'experiments/triad/parallel.sbatch')
            cmd+=(['',''] if prefix is None else [])+[str(path)]
            certificate=path.parent/'Acceptance.json'
            if certificate.exists():
                accepted=read(certificate)
                if accepted.get('manifest_sha256')!=sha(path) or accepted.get('adapter_sha256')!=sha(shared.__file__):raise PermissionError('original bounded acceptance changed')
                cmd.insert(cmd.index(str(ROOT/'experiments/triad/parallel.sbatch')),'--nodelist='+accepted['validated_nodes'][row['index']])
        else:
            r=c['resources'];cmd=['sbatch','--parsable','--no-requeue','--nodes=1','--ntasks=1','--cpus-per-task='+str(r['cpus']),'--mem='+str(r['memory_mib'])+'M','--time=00:30:00','--partition='+r['partition'],'--account='+str(r['account'] or ''),'--qos='+str(r['qos'] or ''),'--chdir='+str(ROOT),'--job-name='+row['run_id'],'--output='+str(ROOT/'logs'/(row['run_id']+'-%j.out')),str(ROOT/'experiments/triad/parallel.sbatch'),action,row['config'],row['run_dir'],'/public2/home/qiuqian/hdl-envs/portable-v2/bin/python',str(row['request_cap']),str(prefix) if prefix is not None else '',str(segment_cap) if segment_cap is not None else '',str(path)]
        commands.append(cmd)
    if not send:return {'submitted':False,'commands':commands,'original_total_request_cap':m['total_request_cap'],'finite_segment_solve_cap':new_solves if prefix is not None else None}
    if m['mode']=='real' and (approved!=m['total_request_cap'] or not allow_api or not allow_solves):raise PermissionError('explicit original aggregate cap/API/solve approval required')
    if (path.parent/'gate/STOP.json').exists() or (path.parent/'Closed.json').exists():raise PermissionError('stopped/closed batch cannot submit')
    if prefix is not None and solve_cap!=new_solves:raise PermissionError('exact inclusive aggregate first+recheck solve cap required')
    if m['mode']=='real' and prefix is None:
        certificate=read(path.parent/'Acceptance.json')
        if not certificate.get('real_dispatch_path_verified') or certificate.get('manifest_sha256')!=sha(path) or certificate.get('adapter_sha256')!=sha(shared.__file__):raise PermissionError('new-version bounded real dispatch acceptance required before full resume')
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
    for row,p,cmd in zip(selected,run_claims,commands):claim(p,{'state':'submission_reserved','run_id':row['run_id'],'command':cmd,'original_cap':row['request_cap'],'automatic_retry':False})
    (ROOT/'logs').mkdir(exist_ok=True);receipts=[]
    try:
        for row,p,cmd in zip(selected,run_claims,commands):
            result=subprocess.run(cmd,check=True,text=True,capture_output=True);job=result.stdout.strip().split(';')[0]
            if not job.isdigit():raise RuntimeError('unknown sbatch receipt; inspect, do not resubmit')
            record={**read(p),'state':'submitted','job_id':job};write(p,record);write(Path(row['run_dir'])/'latest-submission.json',record);receipts.append(record)
    except BaseException:
        stop(path.parent/'gate','unknown/failed submission; all claims retained');raise
    return {'submitted':True,'receipts':receipts,'original_aggregate_cap':m['total_request_cap'],'finite_new_solve_cap':new_solves if prefix is not None else None,'global_API_width':1,'max_active_searches':2}


def certify(path):
    path=Path(path).resolve();m=shared.load(path);info=inspect(path);s=read(path.parent/'gate/ledger.json');jobs=[];hosts=[];nodes=[]
    if info['STOP'] or s['active'] or s['jobs']:raise PermissionError('unknown/active evidence retained')
    expected_sends=sum(2 if r['group']=='fjsp-u' else 1 for r in m['members'])
    for i,row in enumerate(m['members']):
        d=Path(row['run_dir']);cp=read(d/'checkpoint.json');r=read(d/'latest-submission.json');job=r.get('job_id','')
        expected_prefix=2 if row['group']=='fjsp-u' else 1
        if cp['phase']!='paused' or cp.get('completed_tasks',cp.get('cursor'))!=expected_prefix or r['state']!='submitted' or not job.isdigit():raise PermissionError('two settled bounded Slurm prefixes required (EoH1, U whole init wave2)')
        account=subprocess.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode,NodeList'],check=True,text=True,capture_output=True)
        actual=next((x.split('|') for x in account.stdout.splitlines() if x.split('|')[0]==job),None)
        if not actual or actual[:3]!=[job,'COMPLETED','0:0'] or not actual[3] or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.' for ch in actual[3]):raise PermissionError('terminal successful single-node Slurm receipt required')
        nodes.append(actual[3])
        jobs.append(job);ready=read(path.parent/'preflight'/f'ready-{i}.json');hosts.append(ready['host'])
        if ready['job_id']!=job or not read(path.parent/'preflight'/f'fs-pass-{i}.json')['passed']:raise PermissionError('actual job filesystem preflight missing')
    if len(set(jobs))!=2 or len(s['requests'])!=expected_sends or s['peak']!=1 or any(r['state']!='completed' for r in s['requests'].values()):raise PermissionError('exact bounded successful prefix sends and shared peak1 required')
    value={'manifest_sha256':sha(path),'adapter_sha256':sha(shared.__file__),'two_actual_Slurm_jobs':jobs,'hosts':hosts,'validated_nodes':nodes,'scope':'cross_node' if len(set(nodes))==2 else 'same_node','real_dispatch_path_verified':m['mode']=='real','compute_node_mock_verified':m['mode']=='mock','API_requests':expected_sends if m['mode']=='real' else 0,'solves_upper_bound':sum(2*(2 if r['group']=='fjsp-u' else 1)*configuration.load(r['config'],engineering=True)['instance_count'] for r in m['members']) if m['mode']=='real' else 0,'RUN_READY':False,'note':'finite specified topology only; resumes pinned to these nodes, no provider quota/max-throughput claim'}
    claim(path.parent/'Acceptance.json',value);return value


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['plan','mock-plan','check-only','activate','submit','resume','certify','status','pause','close']);ap.add_argument('--spec',type=Path);ap.add_argument('--directory',type=Path);ap.add_argument('--manifest',type=Path);ap.add_argument('--exclusive-hours',type=float);ap.add_argument('--confirm-exclusive-account',action='store_true');ap.add_argument('--submit',action='store_true');ap.add_argument('--approve-requests',type=int);ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--settled-prefix',type=int);ap.add_argument('--approve-segment-solves',type=int);ap.add_argument('--member',type=int,choices=[0,1]);a=ap.parse_args()
    if a.action=='plan':value=plan(a.spec,a.directory,a.exclusive_hours,a.confirm_exclusive_account)
    elif a.action=='mock-plan':value=mock_plan(a.directory)
    elif a.action in ('check-only','status'):value=inspect(a.manifest)
    elif a.action=='activate':
        if shared.load(a.manifest)['mode']=='real' and not a.confirm_exclusive_account:raise PermissionError('explicit all-other-generators-stopped confirmation required')
        shared.activate(a.manifest);value={'activated':True,'API_requests':0,'actual_solves':0}
    elif a.action in ('submit','resume'):value=submit(a.manifest,'resume' if a.action=='resume' else 'run',a.submit,a.approve_requests,a.allow_api,a.allow_solves,a.settled_prefix,a.approve_segment_solves,a.member)
    elif a.action=='certify':value=certify(a.manifest)
    elif a.action=='pause':
        m=shared.load(a.manifest);rows=m['members'] if a.member is None else [m['members'][a.member]]
        value={'pause_requested':[]}
        for row in rows:subprocess.run(argv(row,'pause',a.manifest),check=True);value['pause_requested'].append(row['run_id'])
    else:
        m=shared.load(a.manifest);info=inspect(a.manifest);s=read(a.manifest.parent/'gate/ledger.json')
        if info['STOP'] or (a.manifest.parent/'gate/metrics.lock').exists() or s['active'] or s['jobs'] or any(r['phase'] not in ('completed','paused','initialization_incomplete','expired') or r.get('writer_lock') for r in info['members']):raise PermissionError('unsafe/unknown batch retained; no close')
        lease=Path(m['account_gate'])/'generation.lock'
        if read(lease).get('protocol')!='SHARED:'+sha(a.manifest):raise PermissionError('not this batch lease')
        claim(a.manifest.parent/'Closed.json',{'at':time.time(),'manifest_sha256':sha(a.manifest)});lease.unlink();value={'closed':True,'resume_prohibited':True}
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
