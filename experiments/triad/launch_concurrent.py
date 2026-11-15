#!/usr/bin/env python3
"""Mac terminal thin controller over the existing shared Slurm/asset entrypoints."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import cluster
REMOTE='/public2/home/qiuqian/hdl-deploy/triad-concurrent-prompt-v2-20261115-r8'
BUNDLE=Path('/Users/DDXQL/Developer/transfer-outbox/triad-concurrent-prompt-v2-20261115-r8.zip')
REPORT=ROOT/'reports/concurrent-prompt-v2-20261115'
MOCK='two-search-mock-acceptance'
REAL='first-eoh-501-502'


def invoke(connection,args):
    result=connection.run([cluster.shared.PY,'-s','-B',REMOTE+'/experiments/triad/parallel.py',*args]);return json.loads(result.stdout)


def fetch(connection,name,report):
    m=json.loads(connection.run(['cat',REMOTE+'/plans/'+name+'/Shared.json']).stdout);rows=[]
    for row in m['members']:
        receipt=json.loads(connection.run(['cat',row['run_dir']+'/latest-submission.json']).stdout);job=receipt.get('job_id','')
        if receipt['state']!='submitted' or not job.isdigit():raise ValueError('unknown submission; preserve claims, never retry')
        q=connection.run(['squeue','-h','-j',job,'-o','%i|%T']);a=connection.run(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode,Elapsed,AllocCPUS,MaxRSS,NodeList'])
        (report/(job+'-sacct.psv')).write_text(a.stdout);(report/(job+'-squeue.txt')).write_text(q.stdout)
        state=next((line.split('|') for line in a.stdout.splitlines() if line.split('|')[0]==job),None)
        if q.stdout.strip() or not state or state[1].split()[0] not in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}:raise PermissionError('both jobs must be terminal before batch retrieval; no automatic retry')
        exported=json.loads(connection.run([cluster.shared.PY,'-s','-B','-c',cluster.EXPORT,REMOTE,row['run_dir'],job]).stdout)
        archive=report/(job+'.zip');connection.copy(cluster.shared.HOST+':'+exported['path'],str(archive))
        if sha(archive)!=exported['sha256']:raise ValueError('retrieval ZIP hash differs')
        with zipfile.ZipFile(archive) as z:
            manifest=json.loads(z.read('retrieval-manifest.json'))
            for n,h in manifest['files'].items():
                if Path(n).is_absolute() or '..' in Path(n).parts or hashlib.sha256(z.read(n)).hexdigest()!=h:raise ValueError('unsafe or mismatched retrieval member')
            z.extractall(report/job)
        rows.append({'中文名称':('工程检查：两个Slurm作业无API验收' if name==MOCK else row['group']+'独立搜索')+'（种子'+str(row['seed'])+'）','job_id':job,'Slurm_state':state[1],'exit_code':state[2],'result':str(report/job),'ZIP_sha256':sha(archive),'hashes_verified':True})
    return {'retrieved':True,'members':rows,'local_evidence':str(report),'API_requests':0,'actual_solves':0}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['check-only','stage','mock-submit','mock-status','mock-certify','mock-fetch','real-plan','real-submit','real-status','real-certify','real-fetch','real-resume','real-close','api2-plan','api2-submit','api2-certify','api2-decide'])
    ap.add_argument('--submit',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-requests',type=int);ap.add_argument('--approve-new-requests',type=int);ap.add_argument('--approve-segment-solves',type=int);ap.add_argument('--confirm-exclusive-account',action='store_true');ap.add_argument('--exclusive-hours',type=float);ap.add_argument('--width',type=int,choices=[1,2]);a=ap.parse_args()
    cluster.REMOTE=REMOTE;cluster.BUNDLE=BUNDLE
    if a.action=='check-only':
        value={'中文名称':'三问题独立搜索与共享请求准入准备包','prepared':BUNDLE.exists(),'uploaded':'not_checked','two_actual_searches_verified':False,'API2_adopted':False,'API_requests':0,'actual_solves':0,'next_manual_Mock_budget':{'jobs':2,'CPUs_total':4,'memory_MiB_total':2048,'API_requests':0,'actual_solves':0,'wall_seconds_per_job':1800}}
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    real_submit=a.action in ('real-submit','real-resume','api2-submit')
    if real_submit and (not a.submit or not a.allow_api or not a.allow_solves or a.approve_requests!=2040):raise PermissionError('manual two EoH original2040 approval/API/solve flags required')
    if a.action in ('real-submit','api2-submit') and (a.approve_new_requests!=2 or a.approve_segment_solves!=84):raise PermissionError('this bounded phase requires exactly2 new requests,at most84 first/recheck solves inside original budgets')
    if a.action=='mock-submit' and (not a.submit or a.allow_api or a.allow_solves):raise PermissionError('explicit manual Mock submission with NO API/solve approval required')
    if a.action=='real-plan' and (not a.confirm_exclusive_account or a.exclusive_hours is None or not 48<=a.exclusive_hours<=168):raise PermissionError('fresh all-device exclusion covering48h run and queue required')
    report=REPORT/(a.action+'-'+str(time.time_ns()));report.mkdir(parents=True,exist_ok=False)
    with cluster.shared.Connection() as connection:
        manifest=REMOTE+'/plans/'+(MOCK if a.action.startswith('mock-') else REAL)+'/Shared.json'
        if a.action=='stage':
            result=connection.run([cluster.shared.PY,'-s','-B','-',REMOTE],(ROOT/'experiments/triad/cluster-fjsp/inspect_remote.py').read_text());(report/'inventory.json').write_text(result.stdout)
            info=json.loads(result.stdout)
            if info['commands']['environment']['returncode'] or not info['ancestor_writable']:raise RuntimeError('existing environment or permissions failed; no installation attempted')
            if not json.loads(info['commands']['environment']['stdout'])['python'].startswith('3.12.'):raise RuntimeError('admitted Python3.12 required')
            value=cluster.stage_release(connection,report)
        elif a.action=='mock-submit':
            invoke(connection,['mock-plan','--directory',REMOTE+'/plans/'+MOCK])
            invoke(connection,['activate','--manifest',manifest])
            value=invoke(connection,['submit','--manifest',manifest,'--submit','--settled-prefix','1','--approve-segment-solves','0'])
        elif a.action=='real-plan':
            # The first actual real prefix repeats filesystem checks on its
            # own compute nodes before any model dispatch.
            proof=json.loads(connection.run(['cat',REMOTE+'/plans/'+MOCK+'/Acceptance.json']).stdout)
            if not proof['compute_node_mock_verified']:raise PermissionError('actual two-job compute Mock acceptance required first')
            value=invoke(connection,['plan','--spec',REMOTE+'/configurations/triad-adopted-20261115/pairs/first-eoh-501-502.json','--directory',REMOTE+'/plans/'+REAL,'--confirm-exclusive-account','--exclusive-hours',str(a.exclusive_hours)])
            invoke(connection,['activate','--manifest',manifest,'--confirm-exclusive-account'])
        elif a.action.endswith('-status'):value=invoke(connection,['status','--manifest',manifest])
        elif a.action.endswith('-fetch'):value=fetch(connection,MOCK if a.action.startswith('mock-') else REAL,report)
        elif a.action.endswith('-certify'):value=invoke(connection,['certify','--manifest',manifest,'--phase','2' if a.action.startswith('api2-') else '1'])
        elif a.action=='real-close':value=invoke(connection,['close','--manifest',manifest])
        elif a.action=='api2-plan':
            if a.approve_new_requests!=2 or a.approve_segment_solves!=84:raise PermissionError('API2 is a separate finite2-request/84-solve manual approval')
            value=invoke(connection,['authorize-api2','--manifest',manifest,'--additional-requests','2','--approve-segment-solves','84'])
        elif a.action=='api2-decide':value=invoke(connection,['decide-api2','--manifest',manifest,'--width',str(a.width),'--approve-requests',str(a.approve_requests)])
        else:
            args=['resume' if a.action!='real-submit' else 'submit','--manifest',manifest,'--submit','--allow-api','--allow-solves','--approve-requests','2040']
            if a.action!='real-resume':args+=['--settled-prefix','2' if a.action=='api2-submit' else '1','--approve-segment-solves','84']
            value=invoke(connection,args)
    value.update(local_evidence=str(report),remote_root=REMOTE);write(report/'status.json',value);print(json.dumps(value,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
