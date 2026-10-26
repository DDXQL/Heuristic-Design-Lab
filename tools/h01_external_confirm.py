"""Two frozen U policies, at most 20 new instances; no API/search path.

Minimal per-instance adapter around the unchanged certified T30 worker/collector.
"""
import argparse
from dataclasses import asdict
import multiprocessing as mp
import os
from pathlib import Path
import signal
from statistics import fmean
import subprocess
import sys
import time

from tools import h01_external_data as d
from tools import ind_evo_h01 as old

ROOT=d.ROOT;RUN=d.RUN;REPORT=d.REPORT;MODULE='tools.h01_external_confirm'
read=d.read;write=d.write;sha=d.sha


def now(): return {'wall':time.time(),'monotonic':time.monotonic()}


def tasks(instances):
    rows=[]
    for index,row in enumerate(instances):
        for policy in (('dynamic','equal') if index%2==0 else ('equal','dynamic')):
            rows.append({'task_id':f'{index+1:02d}_{policy}','instance_index':index,
                         'policy':policy,'file':row['file']})
    return rows


def enough_time(current,deadline): return current+90<=deadline


def freeze():
    if (RUN/'Protocol.json').exists():raise ValueError('already frozen; no prepare repeat')
    previous=old.check();state=read(old.RUN/'checkpoint.json');old.ledger(state,previous)
    acceptance=read(REPORT/'Offline_acceptance.json')
    if not acceptance['passed'] or acceptance['real_API'] or acceptance['formal_solves']:
        raise ValueError('offline acceptance required')
    data=read(RUN/'Data_manifest.json');instances=data['instances']
    if not 1<=len(instances)<=20 or instances!=d.select(data['candidate_pool']):raise ValueError('sampling identity')
    champ=state['tasks']['r2_EVO_s16'];p0=next(r for r in read(old.RUN/'P0.json') if r['id']=='MANUAL/init/alpha_050')
    verified=read(old.REPORT/'closeout-v1/Champion_freeze.json')
    if verified['proofs'][1]['UTF8_code_sha256']!=__import__('hashlib').sha256(champ['candidate']['code'].encode()).hexdigest():
        raise ValueError('champion code mismatch')
    assert champ['certified_valid'] and champ['candidate']['key']=='f5992550e506d4708c21b06595ecaa451095f5bf0d83ff9220cd9a88dc4bf215'
    policies={'dynamic':champ['candidate'],'equal':p0['candidate']}
    write(RUN/'Policies.json',policies);write(RUN/'Tasks.json',tasks(instances))
    (RUN/'H_frozen.json').write_bytes((old.RUN/'H_frozen.json').read_bytes())
    write(RUN/'Authorization.json',{'origin':'current user fixed champion out-of-training validation instruction',
        'real_generation_API':False,'new_instances_max':20,'program_instances_max':40,'solve_passes_max':80,
        'policies':['r2_EVO_s16','original_equal_P0'],'no_policy_changes':True,'no_search':True,
        'no_old_campaign_resume':True,'no_push':True,'window_seconds_max':43200,
        'window_basis':'12h upper bound from preceding user authorization, latest fixed plan narrows method scope'})
    sources={**previous['source_files']}
    for name in ('tools/h01_external_confirm.py','tools/h01_external_data.py','tests/test_h01_external_confirm.py',
                 'docs/H01_EXTERNAL_CONFIRMATION_SELECTION_V1.md'):
        sources[name]=sha(ROOT/name)
    protected={**previous['protected_files']}
    assets=[p for p in RUN.rglob('*') if p.is_file()]
    for path in assets:protected[str(path.relative_to(ROOT))]=sha(path)
    protected[str((REPORT/'Offline_acceptance.json').relative_to(ROOT))]=sha(REPORT/'Offline_acceptance.json')
    p={'version':d.NAME,'base_commit':'ad50d411fb73d85cb6e5f3c41416e2ce7333cea9',
       'source_files':sources,'protected_files':protected,'instances':instances,'H_order':previous['H_order'],
       'policies':policies,'solve_seed':501,'interface':old.INTERFACE,'T30':30,'exit_grace':2.0,
       'max_tasks':40,'max_solves':80,'launch_seconds':43200,'task_start_reserve_seconds':90,
       'selection_seed':d.SEED,'distribution':data['distribution'],
       'evaluation':'unchanged cross_feedback_ab_execute.worker + baseline_supplemental T30 collect/classify; independent one-instance worker per task; no trace replay',
       'metric':'complete selected-list mean(-Cmax/unrounded V5 LB); higher is better',
       'failure':'confirmed ordinary timeout/runtime invalid => no retry, keep all independent tasks; any missing row => complete policy Fitness null; unknown identity/exit/reservation/recheck/clock gap => Stop',
       'analysis':'all frozen instances primary; W/L/T; delta and relative mean ratio; gross gain/loss concentration; raw sum only supplement; optional stratified paired percentile bootstrap 20000 seed2026102618',
       'old_training_references':{'dynamic':champ['fitness'],'equal':p0['fitness']}}
    write(RUN/'Protocol.json',p);(RUN/'Protocol.sha256').write_text(sha(RUN/'Protocol.json')+'\n')
    write(RUN/'Expected_solver_identity.json',old.certified.witness(p))
    write(RUN/'Expected_controller_identity.json',old.certified.attest_module(MODULE,p))
    write(RUN/'checkpoint.json',{'protocol_sha256':sha(RUN/'Protocol.json'),'cursor':0,'phase':'prepared','tasks':{}})
    print({'frozen':len(instances),'program_instances':len(tasks(instances)),'protocol_sha256':sha(RUN/'Protocol.json')})


def check():
    old.check()
    p=read(RUN/'Protocol.json')
    if sha(RUN/'Protocol.json')!=(RUN/'Protocol.sha256').read_text().strip():raise ValueError('protocol changed')
    for name,h in {**p['source_files'],**p['protected_files']}.items():
        if sha(ROOT/name)!=h:raise ValueError('source/data identity mismatch: '+name)
    if p['policies']!=read(RUN/'Policies.json') or read(RUN/'Tasks.json')!=tasks(p['instances']):raise ValueError('frozen tasks/policies changed')
    if old.certified.witness(p)['identity']!=read(RUN/'Expected_solver_identity.json')['identity']:raise ValueError('solver loaded identity')
    if old.certified.attest_module(MODULE,p)!=read(RUN/'Expected_controller_identity.json'):raise ValueError('controller loaded identity')
    assert (p['T30'],p['exit_grace'],p['solve_seed'],p['max_tasks'],p['max_solves'])==(30,2.,501,40,80)
    return p


def ledger(s,p):
    plan=read(RUN/'Tasks.json')
    if s['protocol_sha256']!=sha(RUN/'Protocol.json') or len(s['tasks'])>40:raise ValueError('ledger identity/budget')
    if set(s['tasks'])!={r['task_id'] for r in plan[:s['cursor']]}:raise ValueError('unknown reservation; never repeat')
    for tid,t in s['tasks'].items():
        if t['status']!='completed':raise ValueError('unknown task terminal')
        path=RUN/t['result_path']
        if sha(path)!=t['result_sha256']:raise ValueError('saved result changed')
        old.validate_result(read(path),[p['instances'][t['instance_index']]],'modern')


def run():
    p=check()
    if (RUN/'End_summary.json').exists():return
    if (RUN/'Stop.json').exists():raise ValueError('persistent Stop, no automatic restart')
    fd=os.open(RUN/'.execution.lock',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(str(os.getpid()))
    signal.signal(signal.SIGHUP,signal.SIG_IGN);keep=None;normal=False;s=read(RUN/'checkpoint.json')
    try:
        ledger(s,p)
        if not (RUN/'Run_clock.json').exists():
            t=now();write(RUN/'Run_clock.json',{'start':t,'deadline':t['wall']+p['launch_seconds']})
        clock=read(RUN/'Run_clock.json')
        if clock['deadline']!=clock['start']['wall']+43200:raise ValueError('persistent deadline changed')
        keep=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        write(RUN/'Run_identity.json',{'pid':os.getpid(),'ppid':os.getppid(),'sid':os.getsid(0),'start':now()})
        policies=read(RUN/'Policies.json');members=tuple(old.checked_candidate(r['candidate'],'h') for r in read(RUN/'H_frozen.json')['members'])
        expected={**p['source_files'],**p['protected_files']};plan=read(RUN/'Tasks.json');s['phase']='running'
        for task in plan[s['cursor']:]:
            p=check();ledger(s,p)
            if not enough_time(time.time(),clock['deadline']):s['phase']='deadline_partial';break
            tid=task['task_id'];folder=RUN/'evaluations'/tid;folder.mkdir(parents=True,exist_ok=False)
            spec=p['instances'][task['instance_index']];path=RUN/spec['relative_path']
            instance=old.certified.s.v2.load_instance(path);beg=now()
            s['tasks'][tid]={**task,'status':'reserved','started':beg,'reserved_instances':1,'reserved_solves':2};write(RUN/'checkpoint.json',s)
            candidate=old.checked_candidate(policies[task['policy']],'U')
            payload={'folder':str(folder),'binding':p,'candidate':asdict(candidate),'train_paths':[str(path)]}
            write(folder/'Input_receipt.json',{'candidate':asdict(candidate),'instance':spec,'H_order':p['H_order'],
                'protocol_sha256':sha(RUN/'Protocol.json'),'worker':'tools.cross_feedback_ab_execute.worker'})
            start_files={name:sha(ROOT/name) for name in expected}
            rows,failure,life=old.certified.collect(mp.get_context('spawn'),old.certified.worker,payload,members,[instance],[spec['file']],30,(1,),lambda row:write(folder/'lifecycle.json',row))
            result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
                    'total_instances':1,'instances':rows,'primary_evaluation_seconds':time.monotonic()-beg['monotonic'],**(failure or {})}
            write(folder/'raw_result.json',result)
            boundary=old.certified.certify(result,dict(before=read(folder/'before.json') if (folder/'before.json').exists() else None,
                after=read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
                expected_identity=read(RUN/'Expected_solver_identity.json')['identity'],expected_files=expected,
                start_files=start_files,end_files={name:sha(ROOT/name) for name in expected},worker_failure=(folder/'worker_failure.json').exists()))
            write(folder/'boundary.json',boundary)
            if boundary['decision']=='stop':raise ValueError('certification Stop: '+boundary['reason'])
            old.validate_result(result,[spec],'modern');end=now()
            gap=(end['wall']-beg['wall'])-(end['monotonic']-beg['monotonic'])
            if abs(gap)>2:
                write(folder/'Clock_quarantine.json',{'start':beg,'end':end,'gap':gap});raise ValueError('clock gap; no repeat')
            result['boundary']=boundary;write(folder/'result.json',result)
            s['tasks'][tid].update(status='completed',valid=result['valid'],finished=end,
                result_path=str((folder/'result.json').relative_to(RUN)),result_sha256=sha(folder/'result.json'))
            s['cursor']+=1;write(RUN/'checkpoint.json',s)
            with (RUN/'Events.jsonl').open('a') as f:f.write(__import__('json').dumps({'event':'task_committed','task_id':tid,'valid':result['valid'],**end})+'\n');f.flush();os.fsync(f.fileno())
        else:s['phase']='completed'
        write(RUN/'checkpoint.json',s);normal=True
    except BaseException as exc:
        s['phase']='stopped';write(RUN/'checkpoint.json',s)
        write(RUN/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc),'at':now(),'automatic_retry':False})
    finally:
        if keep is not None:
            keep.terminate()
            try:keep.wait(timeout=2)
            except subprocess.TimeoutExpired:keep.kill();keep.wait()
        write(RUN/'End_summary.json',{'phase':s['phase'],'cursor':s['cursor'],'end':now(),
              'caffeinate_cleaned':keep is not None,'lock_retained':not normal,'API_calls':0})
        if normal:(RUN/'.execution.lock').unlink()
        from tools.h01_external_report import report
        try:report()
        except Exception as exc:write(RUN/'Report_error.json',{'error_type':type(exc).__name__,'error':str(exc)})


def launch():
    check()
    if any((RUN/n).exists() for n in ('Launch_identity.json','End_summary.json','.execution.lock')):raise ValueError('already launched/unknown; no automatic replay')
    env={**os.environ,'PYTHONPATH':str(ROOT/'code')+':'+str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'}
    pid=old.certified.detach([sys.executable,'-B','-c',f'from {MODULE} import run;run()'],RUN/'Console.log',env=env)
    write(RUN/'Launch_identity.json',{'pid':pid,'at':now(),'method':'existing detached session, files, SIGHUP ignore'})
    print({'pid':pid,'tasks':len(read(RUN/'Tasks.json')),'API_calls':0})


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=('freeze','check','launch','run'));a=ap.parse_args()
    if a.stage=='freeze':freeze()
    elif a.stage=='check':check();print('PASS')
    elif a.stage=='launch':launch()
    else:run()
