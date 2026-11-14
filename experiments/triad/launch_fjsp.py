#!/usr/bin/env python3
"""FJSP-first manual deployment; same admitted SSH, Slurm and retrieval helpers."""
import argparse
import base64
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile
from contextlib import redirect_stdout
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import cluster,batch,configuration,registration,review
HERE=ROOT/'experiments/triad/cluster-fjsp';REPORT=ROOT/'reports/cluster-launch-20261114';LATEST=REPORT/'latest-preparation.json'
PROBE_EXPORT='''import json,pathlib,hashlib,zipfile,sys,time
root=pathlib.Path(sys.argv[1]);phase=sys.argv[2];folder=root/'runs/cluster-api-concurrency-20261114'/('phase'+phase)
if phase not in ('1','2'):raise SystemExit('invalid phase')
out=root/'exports'/('API-probe-phase'+phase+'-'+str(time.time_ns())+'.zip');out.parent.mkdir(exist_ok=True)
files={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file() and not p.is_symlink() and not p.name.endswith('.tmp')}
with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for n in files:z.write(folder/n,n)
 z.writestr('retrieval-manifest.json',json.dumps({'files':files,'scope':'engineering API probe only, no research population'}))
print(json.dumps({'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
'''


def local_plan(exclusive_hours=None,confirm=False):
    doc=read(HERE/'review.pending.json')
    if exclusive_hours is not None:
        if not confirm or not 48<=exclusive_hours<=168:raise PermissionError('fresh explicit all-device exclusion must cover the proposed 48h search plus queue time')
        doc['common']['account_exclusion']={'scope':'all_devices_sharing_account','confirmation':'operator explicitly confirms all their other account generation tasks stopped for this period','valid_until':time.time()+exclusive_hours*3600}
    key=__import__('hashlib').sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()[:12];folder=ROOT/'configurations'/('fjsp-priority-'+key);doc['campaign_id']='fjsp-priority-'+key
    if not folder.exists():
        folder.mkdir(parents=True);write(folder/'review.json',doc)
        subprocess.run([sys.executable,'-s','-B',str(ROOT/'experiments/triad/review.py'),'--review',str(folder/'review.json'),'--output',str(folder/'reviewed'),'--groups','fjsp-eoh','fjsp-u'],check=True,text=True,capture_output=True)
    campaign=folder/'reviewed/campaign.json';plan_dir=ROOT/'plans'/doc['campaign_id'];p=batch.materialize(campaign,plan_dir)
    row=batch.select(p,'fjsp-u',501)[0]
    if not row.get('existing_registration'):
        receipt=registration.register(row,configuration.load(row['config']),True);row['existing_registration']=receipt;write(plan_dir/'registrations'/(row['run_id']+'.json'),receipt);write(plan_dir/'Batch.json',p)
    return {'campaign':str(campaign),'local_batch':str(plan_dir),'batch_name':doc['campaign_id'],'existing_receipt':str(plan_dir/'registrations'/(row['run_id']+'.json'))}


def check():
    approval=read(ROOT/'experiments/triad/repetition-approval.json');draft=read(HERE/'review.pending.json');provider=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['client_binding'];template=read(ROOT/'preparations/triad/fjsp/U_frozen_template.json')['settings']
    return {'approved_repetitions':approval,'priority':'fjsp-eoh seed501, then new FJSP U seeds502/503 when their profile is adopted','FJSP_EoH_adopted_parameters':{'population':10,'initialization_HTTP_cap':20,'evolution_attempts':1000,'total_request_cap':1020,'per_attempt':1,'automatic_retry':0,'native_initialization_can_finish_before_20':True,'project_N_finite_gate':True},'provider_equals_actual_U501':provider['provider']==template['provider'],'remote_status':'not inspected in this session; interactive prepare needed','proposed_resources':draft['common']['resources'],'proposed_window_seconds':draft['common']['window_seconds'],'account_exclusion':draft['common']['account_exclusion'],'pending':['fresh remote environment/permissions/account/QOS/queue and credential metadata','fresh all-device exclusion; account sole user does not prove other scripts stopped','API probe stage1: separate 4-send approval and two-job result; stage2 optional','FJSP U new-seed scientific budget adoption; TSP LKH and OBP assets separate'],'API_requests':0,'solves':0,'RUN_READY':False}


def remote_prepare(exclusive_hours,confirm):
    if not cluster.BUNDLE.exists():raise FileNotFoundError('new frozen r5 package is not built yet; no interactive login attempted')
    binding=local_plan(exclusive_hours,confirm);report=REPORT/('prepare-'+str(time.time_ns()));report.mkdir(parents=True)
    result={**binding,'prepared':True,'uploaded':False,'compute_node_verified':False,'RUN_READY':False,'API_requests':0,'actual_solves':0,'local_evidence':str(report)}
    try:
        with cluster.shared.Connection() as c:
            probe=c.run([cluster.shared.PY,'-s','-B','-',cluster.REMOTE],(HERE/'inspect_remote.py').read_text());(report/'current-inventory.json').write_text(probe.stdout);inventory=json.loads(probe.stdout)
            if inventory['commands']['environment']['returncode'] or not inventory['ancestor_writable']:raise RuntimeError('existing environment/permissions failed; no installation attempted')
            version=json.loads(inventory['commands']['environment']['stdout'])['python']
            if not version.startswith('3.12.'):raise RuntimeError('frozen H/source identity requires the admitted Python3.12 environment; no silent AST/key migration')
            result.update(cluster.stage_release(c,report));result.update(cluster.sync_config(c,binding['campaign'],report))
            digest=sha(binding['existing_receipt']);target=cluster.REMOTE+'/registrations/existing-501-'+digest+'.json'
            c.run([cluster.shared.PY,'-s','-B','-c',cluster.SAVE,target,base64.b64encode(Path(binding['existing_receipt']).read_bytes()).decode()])
            c.run([cluster.shared.PY,'-s','-B',cluster.REMOTE+'/experiments/triad/batch.py','import-existing','--batch',result['remote_batch'],'--experiment','fjsp-u','--seed','501','--receipt',target,'--receipt-sha256',digest,'--accept-existing-completed'])
            check=c.run([cluster.shared.PY,'-s','-B',cluster.REMOTE+'/experiments/triad/batch.py','check-only','--batch',result['remote_batch'],'--experiment','fjsp-eoh','--seed','501']);(report/'first-FJSP-check-only.json').write_text(check.stdout)
            first=json.loads(check.stdout)[0];result.update(first_FJSP_pending=first['pending'],first_FJSP_check_only_ready=first['ready'],credential_metadata=inventory['credential'],other_jobs=inventory['commands']['queue'])
            # API/probe admission still needs the user's manual command, never implied by deployment.
        write(LATEST,result);write(report/'result.json',result);return result
    except Exception as e:
        result.update(error_type=type(e).__name__,error=str(e),automatic_retry=False);write(report/'result.json',result);raise


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['check-only','prepare','probe-submit','probe-status','probe-fetch','submit-first','query','pause','resume','fetch']);ap.add_argument('--phase',type=int,default=1);ap.add_argument('--submit',action='store_true');ap.add_argument('--approve-sends',type=int);ap.add_argument('--exclusive-hours',type=float);ap.add_argument('--confirm-exclusive-account',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-budget',type=int);ap.add_argument('--pause-after-attempts',type=int);ap.add_argument('--approve-segment-solves',type=int);a=ap.parse_args()
    if a.action=='check-only':result=check()
    elif a.action=='prepare':
        if sys.version_info[:2]!=(3,12):raise RuntimeError('use mac-portability-env-v2 Python3.12 for frozen H identity; plotting Python3.13 is separate')
        result=remote_prepare(a.exclusive_hours,a.confirm_exclusive_account)
    elif a.action.startswith('probe-'):
        if a.action=='probe-submit' and a.submit:
            previous=read(LATEST)
            if not previous.get('uploaded') or not previous.get('credential_metadata',{}).get('runtime_acceptable'):raise PermissionError('current deployment/credential metadata not ready; no submission')
        args=[cluster.shared.PY,'-s','-B',cluster.REMOTE+'/experiments/triad/probe_submit.py','submit' if a.action=='probe-submit' else 'status','--phase',str(a.phase)]
        if a.submit:args+=['--submit','--approve-sends',str(a.approve_sends),'--exclusive-hours',str(a.exclusive_hours)]+(['--confirm-exclusive-account'] if a.confirm_exclusive_account else [])
        with cluster.shared.Connection() as c:
            answer=c.run(args);result=json.loads(answer.stdout)
            if a.action=='probe-fetch':
                # Query both recorded Slurm identities before snapshotting the folder.
                script='import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); print(json.dumps([json.loads(f.read_text()) for f in p.glob("submissions/*.json")]))'
                claims=json.loads(c.run([cluster.shared.PY,'-s','-B','-c',script,cluster.REMOTE+'/runs/cluster-api-concurrency-20261114/phase'+str(a.phase)]).stdout)
                for item in claims:
                    if item['state']!='submitted':raise PermissionError('unknown submission; preserve and inspect, no final fetch claim')
                    queue=c.run(['squeue','-h','-u','qiuqian','-o','%i|%T'])
                    if any(line.split('|')[0]==item['job_id'] for line in queue.stdout.splitlines()):raise PermissionError('probe job still active; no final retrieval yet')
                packet=json.loads(c.run([cluster.shared.PY,'-s','-B','-c',PROBE_EXPORT,cluster.REMOTE,str(a.phase)]).stdout);report=REPORT/('probe-fetch-'+str(time.time_ns()));report.mkdir(parents=True);local=report/'result.zip';c.copy(cluster.shared.HOST+':'+packet['path'],str(local))
                if sha(local)!=packet['sha256']:raise ValueError('probe transfer hash mismatch')
                with zipfile.ZipFile(local) as z:
                    manifest=json.loads(z.read('retrieval-manifest.json'))
                    for name,h in manifest['files'].items():
                        p=Path(name)
                        if p.is_absolute() or '..' in p.parts or __import__('hashlib').sha256(z.read(name)).hexdigest()!=h:raise ValueError('unsafe/mismatched probe member')
                    z.extractall(report/'retrieved')
                result.update(retrieved=True,result_hashes_verified=True,local_evidence=str(report));write(report/'result.json',result)
    elif a.action=='submit-first':
        bound=read(LATEST)
        if not a.submit or not a.allow_api or not a.allow_solves or a.approve_budget!=1020:raise PermissionError('manual original1020 request approval, API and solve flags required')
        with cluster.shared.Connection() as c:
            passed=c.run([cluster.shared.PY,'-s','-B',cluster.REMOTE+'/experiments/triad/probe_submit.py','status','--phase','1']);status=json.loads(passed.stdout)
            if not status['passed']:raise PermissionError('phase1 has not passed; phase2 is not required')
            gate='/public2/home/qiuqian/hdl-account-gates/leafapi-gpt61sol-serial-v1/generation.lock'
            if c.run(['test','-e',gate],check=False).returncode==0:raise PermissionError('another generation/probe account lease exists; never clear it or submit over it')
            args=[cluster.shared.PY,'-s','-B',cluster.REMOTE+'/experiments/triad/slurm.py','run','--batch',bound['remote_batch'],'--experiment','fjsp-eoh','--seed','501','--submit','--allow-api','--allow-solves','--approve-budget','1020']
            if a.pause_after_attempts is not None:args+=['--pause-after-attempts',str(a.pause_after_attempts),'--approve-segment-solves',str(a.approve_segment_solves)]
            answer=c.run(args);result=json.loads(answer.stdout)
    else:
        bound=read(LATEST);args=[sys.executable,'-s','-B',str(ROOT/'experiments/triad/cluster.py'),a.action,'--batch-name',bound['batch_name'],'--experiment','fjsp-eoh','--seed','501']
        if a.action=='resume':args+=['--submit','--allow-api','--allow-solves','--approve-budget',str(a.approve_budget)]
        return subprocess.run(args).returncode
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
