#!/usr/bin/env python3
"""Mac-only bridge to frozen R13. Default is local, no SSH or run-state writes."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import write
from experiments.triad import cluster,launch_concurrent
REMOTE='/public2/home/qiuqian/hdl-deploy/triad-tsp-lkh-candidate-20261117-r13'
PLAN=REMOTE+'/plans/six-tsp501/Shared.json'
VERIFY='/public2/home/qiuqian/hdl-tools/r11-stop-audit-20261118/manage.py'
VERIFY_SHA='ed21a29f6f8af4ab6136c993ee5b8a0f4a6074925264e5fe7749572099ae7ad9'
INSPECT=r'''import json,pathlib,sys
r=pathlib.Path(sys.argv[1]);p=r/'plans/six-tsp501/Shared.json'
if not p.exists():print(json.dumps({'plan_exists':False,'current_run_ready':False}));raise SystemExit(0)
m=json.loads(p.read_text());assert m['mode']=='real' and m['total_request_cap']==2040 and m['global_API_width']==1
assert len(m['members'])==2 and {x['group'] for x in m['members']}=={'tsp-u','tsp-eoh'} and all(x['seed']==501 and x['request_cap']==1020 for x in m['members'])
for x in m['members']:
 c=json.loads(pathlib.Path(x['config']).read_text());assert c['search_seed']==501 and c['initialization_request_cap']==20 and c['evolution_request_cap']==1000 and c['api_attempt_cap']==1020
 assert c['instance_count']==20 and c['population_size']==(5 if x['group']=='tsp-u' else 10)
print(json.dumps({'plan_exists':True,'activated':(p.parent/'Activation.json').exists(),'STOP':(p.parent/'gate/STOP.json').exists(),'closed':(p.parent/'Closed.json').exists(),'members':m['members']}))
'''
LOGS=r'''import json,pathlib,sys,collections
m=json.loads(pathlib.Path(sys.argv[1]).read_text());out=[]
for r in m['members']:
 d=pathlib.Path(r['run_dir']);cp=d/'checkpoint.json'
 if not cp.exists():out.append({'group':r['group'],'phase':'not_started'});continue
 s=json.loads(cp.read_text());jp=d/'API_attempts.json';j=json.loads(jp.read_text()) if jp.exists() else {'api_attempts':{}}
 a=list(j['api_attempts'].values());events=d/'Events.jsonl'
 with events.open() if events.exists() else __import__('contextlib').nullcontext([]) as f:tail=list(collections.deque(f,maxlen=5))
 out.append({'group':r['group'],'run_dir':str(d),'phase':s['phase'],'initialization_attempts':s['eoh']['initialization_requests'],'evolution_attempts':s['eoh']['operator_cursor'],'charged_requests':len(a),'original_cap':1020,'pause_reason':s.get('pause_reason'),'latest_failed_metadata':[(x.get('metadata') or {}) for x in a if x['status']!='completed'][-2:],'event_tail':tail})
print(json.dumps({'members':out,'API_requests_by_inspection':0,'actual_solves_by_inspection':0}))
'''


def command(action):
    args=['--manifest',PLAN]
    if action=='prefix-submit':return [cluster.shared.PY,'-s','-B',REMOTE+'/experiments/triad/parallel.py','submit',*args,'--submit','--allow-api','--allow-solves','--approve-requests','2040','--settled-prefix','1','--approve-segment-solves','80']
    if action=='continue':return [cluster.shared.PY,'-s','-B',REMOTE+'/experiments/triad/parallel.py','resume',*args,'--submit','--allow-api','--allow-solves','--approve-requests','2040']
    return [cluster.shared.PY,'-s','-B',REMOTE+'/experiments/triad/parallel.py','certify' if action=='certify' else 'status',*args]


def verify(connection,report):
    check='import hashlib,pathlib,sys;assert hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()==sys.argv[2],"management verifier identity differs"'
    connection.run([cluster.shared.PY,'-s','-B','-c',check,VERIFY,VERIFY_SHA])
    raw=connection.run([cluster.shared.PY,'-s','-B',VERIFY,'verify-handoff']).stdout
    (report/'handoff.json').write_text(raw);v=json.loads(raw)
    if v.get('handoff_proof_valid') is not True or v.get('scientific_status')!='incomplete' or v.get('account_unoccupied_at_check') is not True or v.get('fixture_only') is not False or v.get('new_task_authorized') is not False:
        raise PermissionError('real safe handoff/account-unoccupied contract not satisfied')
    return v


def operate(connection,a,report):
    if a.action=='handoff':return verify(connection,report)
    if a.action in ('continue','certify'):
        state=json.loads(connection.run([cluster.shared.PY,'-s','-B','-c',INSPECT,REMOTE]).stdout)
        if not state['plan_exists'] or state['STOP'] or state['closed']:raise PermissionError('original R13 plan absent/stopped/closed; no submit or certificate')
    if a.action in ('prefix-preview','prefix-submit'):
        handoff=verify(connection,report)
        state=json.loads(connection.run([cluster.shared.PY,'-s','-B','-c',INSPECT,REMOTE]).stdout)
        if a.action=='prefix-preview':return {'handoff':handoff,'plan':state,'command':command('prefix-submit'),'current_run_ready':False,'manual_execution_approval_required':True,'prefix_requests_max':2,'inclusive_prefix_solves_max':80}
        if not state['plan_exists']:
            if not a.create_plan:raise PermissionError('plan absent; explicit --create-plan required; no automatic preparation')
            connection.run([cluster.shared.PY,'-s','-B',REMOTE+'/experiments/triad/six_ops.py','prepare','--batch','tsp501','--confirm-exclusive-account','--exclusive-hours',str(a.exclusive_hours)])
            state=json.loads(connection.run([cluster.shared.PY,'-s','-B','-c',INSPECT,REMOTE]).stdout)
        if state['activated']:raise PermissionError('already activated plan; inspect original ownership/submissions, never reactivate or repeat prefix')
        if not a.activate_plan:raise PermissionError('explicit --activate-plan required before first prefix')
        connection.run([cluster.shared.PY,'-s','-B',REMOTE+'/experiments/triad/parallel.py','activate','--manifest',PLAN,'--confirm-exclusive-account'])
    if a.action=='fetch':
        launch_concurrent.REMOTE=REMOTE
        return launch_concurrent.fetch(connection,'six-tsp501',report)
    if a.action=='logs':return json.loads(connection.run([cluster.shared.PY,'-s','-B','-c',LOGS,PLAN]).stdout)
    if a.action=='status':
        value=json.loads(connection.run(command('status')).stdout)
        queue=connection.run(['squeue','-u','qiuqian','-o','%.18i %.10T %.10M %R']).stdout
        (report/'squeue.txt').write_text(queue);value['squeue']=queue;return value
    return json.loads(connection.run(command(a.action)).stdout)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',nargs='?',default='check-only',choices=['check-only','handoff','prefix-preview','prefix-submit','certify','continue','status','logs','fetch'])
    for f in ('submit','allow-api','allow-solves','confirm-exclusive-account','create-plan','activate-plan'):p.add_argument('--'+f,action='store_true')
    p.add_argument('--approve-requests',type=int);p.add_argument('--approve-prefix-requests',type=int);p.add_argument('--approve-prefix-solves',type=int);p.add_argument('--exclusive-hours',type=float)
    a=p.parse_args(argv)
    if a.action=='check-only':
        print(json.dumps({'local_only':True,'remote_root':REMOTE,'verifier':VERIFY,'run_identity':'R13 TSP U501+EoH501; never migrated to R14','commands':{k:command(k) for k in ('prefix-submit','certify','continue','status')},'API_requests':0,'actual_solves':0,'SSH_attempts':0,'current_account_state':'unknown','current_plan_exists':'unknown','current_run_ready':False},ensure_ascii=False,indent=2));return 0
    if a.action in ('prefix-submit','continue'):
        if not (a.submit and a.allow_api and a.allow_solves and a.approve_requests==2040):raise PermissionError('separate manual submission/API/solve/original2040 authorization required')
        if a.action=='prefix-submit' and (a.approve_prefix_requests!=2 or a.approve_prefix_solves!=80 or not a.confirm_exclusive_account or a.exclusive_hours is None or not 48<=a.exclusive_hours<=168):raise PermissionError('first prefix requires explicit2 requests/80 inclusive solves and fresh48..168h all-device agreement')
    report=ROOT/'reports/r13-tsp-mac-20261118'/(a.action+'-'+str(time.time_ns()));report.mkdir(parents=True)
    try:
        with cluster.shared.Connection() as connection:value=operate(connection,a,report)
        value.update(local_evidence=str(report),remote_root=REMOTE,automatic_retry=False)
        write(report/'status.json',value);print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    except Exception as e:
        write(report/'ERROR.json',{'error_type':type(e).__name__,'error':str(e),'automatic_retry':False})
        raise


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False}),file=sys.stderr);raise SystemExit(2)
