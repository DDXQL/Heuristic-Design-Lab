"""Human-authorized single API recovery probe, then original eight slots only.

Keeps the original two-hour renewal deadline. Does not regenerate six-attempt
failures, switch model, alter prompts or remove any unknown lock/reservation.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
from tools import ind_evo_h01_continue as c

x=c.x;R=c.C/'recovery-v1';MODULE='tools.ind_evo_h01_recover'


def prepare():
    if R.exists():raise ValueError('recovery already exists; no reset')
    p,b=c.check();s=x.read(x.RUN/'checkpoint.json');x.ledger(s,p)
    stop=x.read(c.C/'Stop.json');end=x.read(c.C/'End_summary.json')
    if stop['error']!='three consecutive failed logical transports; API unavailable' or s['cursor']!=112 or end['cursor']!=112:
        raise ValueError('only known fully classified 503 Stop is eligible')
    journals={f.name:x.read(f) for f in (x.RUN/'journals').glob('*.json')}
    if any(a['status'] not in ('completed','failed') for j in journals.values() for a in j['api_attempts'].values()):
        raise ValueError('unknown API state; no recovery')
    oldlock=x.RUN/'.execution.lock';lock=x.read(oldlock)
    try:os.kill(lock['pid'],0)
    except ProcessLookupError:pass
    else:raise ValueError('previous controller still exists; do not remove lock')
    remaining=x.read(x.RUN/'Tasks.json')[112:]
    assert len(remaining)==8 and remaining[0]['position']==113 and remaining[-1]['position']==120
    assert x.POLICY['logical_candidate_cap']==20 and x.POLICY['api_attempt_cap']==30 and x.POLICY['per_candidate_attempt_cap']==2
    clock=x.read(c.C/'Run_clock.json');assert clock['deadline']==clock['start']['wall']+7200
    R.mkdir();(R/'initial').mkdir()
    (R/'initial/checkpoint.json').write_bytes((x.RUN/'checkpoint.json').read_bytes())
    for name in journals:(R/'initial'/name).write_bytes((x.RUN/'journals'/name).read_bytes())
    authority={'origin':'current direct human request after six HTTP503: 可以再重试一下，或者自行针对并尝试解决',
        'approved':True,'scope':'one next planned candidate as recovery probe; on full response continue remaining original slots',
        'remaining_planned_slots':8,'no_regeneration_of_failed_slots':True,'same_existing_2h_deadline':clock['deadline'],
        'no_model_switch_no_recharge_no_budget_reset':True,'preserve_original_503_Stop_and_known_lock_record':True}
    x.write(R/'Authorization.json',authority)
    binding={'source_sha256':x.sha(x.ROOT/'tools/ind_evo_h01_recover.py'),
        'base_continuation_binding_sha256':x.sha(c.C/'Binding.json'),
        'prior_Stop_sha256':x.sha(c.C/'Stop.json'),'prior_end_sha256':x.sha(c.C/'End_summary.json'),
        'clock_sha256':x.sha(c.C/'Run_clock.json'),'authority_sha256':x.sha(R/'Authorization.json'),
        'initial_tasks_digest':x.digest(s['tasks']),'remaining_tasks':remaining,
        'initial_API_attempts':sum(len(j['api_attempts']) for j in journals.values()),
        'offline_assertions':'exact suffix8, inherited20/30/2 limits, known terminal503 only, immutable2h clock'}
    x.write(R/'Binding.json',binding);(R/'Binding.sha256').write_text(x.sha(R/'Binding.json')+'\n')
    x.write(R/'Loaded_identity.json',x.certified.attest_module(MODULE,{'source_files':{'tools/ind_evo_h01_recover.py':binding['source_sha256']}}))
    # Authenticated terminal controller, all request/evaluation states resolved.
    # Rename retains the original lock evidence; no unknown lock is deleted.
    oldlock.rename(R/'Known_terminal_previous_lock.json')
    check();print('RECOVERY_READY',len(remaining),'existing_deadline',clock['deadline'])


def check():
    p,b=c.check();a=x.read(R/'Binding.json')
    if x.sha(R/'Binding.json')!=(R/'Binding.sha256').read_text().strip():raise ValueError('recovery binding changed')
    for f,k in [(c.C/'Binding.json','base_continuation_binding_sha256'),(c.C/'Stop.json','prior_Stop_sha256'),
                (c.C/'End_summary.json','prior_end_sha256'),(c.C/'Run_clock.json','clock_sha256'),(R/'Authorization.json','authority_sha256')]:
        if x.sha(f)!=a[k]:raise ValueError('preserved recovery evidence changed')
    if x.sha(x.ROOT/'tools/ind_evo_h01_recover.py')!=a['source_sha256']:raise ValueError('recovery source changed')
    if x.certified.attest_module(MODULE,{'source_files':{'tools/ind_evo_h01_recover.py':a['source_sha256']}})!=x.read(R/'Loaded_identity.json'):
        raise ValueError('recovery loaded code mismatch')
    initial=x.read(R/'initial/checkpoint.json');live=x.read(x.RUN/'checkpoint.json')
    if x.digest({k:live['tasks'][k] for k in initial['tasks']})!=a['initial_tasks_digest']:raise ValueError('112 prefix changed')
    for f in (R/'initial').glob('r*_*.json'):
        old=x.read(f);new=x.read(x.RUN/'journals'/f.name)
        if c.prefix_digest(new,old)!=c.prefix_digest(old,old):raise ValueError('115-attempt prefix changed')
    return p,a


def run():
    p,a=check()
    if (R/'End_summary.json').exists() or (R/'Stop.json').exists():raise ValueError('one-shot recovery already ended')
    fd=os.open(x.RUN/'.execution.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'pid':os.getpid(),'scope':'explicit API recovery probe'},f)
    signal.signal(signal.SIGHUP,signal.SIG_IGN);s=x.read(x.RUN/'checkpoint.json');keep=None;wire=None;normal=False
    try:
        x.ledger(s,p);clock=x.read(c.C/'Run_clock.json');s['recovery_binding_sha256']=x.sha(R/'Binding.json');s['phase']='recovery_running'
        x.write(x.RUN/'checkpoint.json',s)
        if x.time.time()+1294>clock['deadline']:raise x.BudgetStop('existing two-hour deadline has insufficient completion reserve')
        keep=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        from fjsp_usage.research_real.leafapi import load_local_key
        os.environ['LEAFAPI_API_KEY']=load_local_key(x.ROOT.parent/'FJSP-Heuristic-Research/.env.leafapi.local')
        wire=x.WireRecorder(x.JsonCandidateTransport(x.config(p)),x.RUN/'wire_responses',verify=check)
        transport=x.Transport(wire,clock['deadline'])
        js={u:x.AttemptJournal(x.RUN/'journals'/(u+'.json'),config=x.config(p),context=x.sha(x.RUN/'Protocol.json'),
            phase=x.NAME+'/'+u,transport=transport) for u in s['units']}
        members=tuple(x.checked_candidate(m['candidate'],'h') for m in x.read(x.RUN/'H_frozen.json')['members'])
        tasks=x.read(x.RUN/'Tasks.json');x.event('human_authorized_API_recovery_probe',cursor=112,deadline=clock['deadline'])
        x.metadata('recovery1_start',wire.secret)
        while s['cursor']<120:
            check();x.ledger(s,p)
            if x.time.time()+1294>clock['deadline']:s['phase']='recovery_deadline_partial';break
            if (x.RUN/'Pause_request.json').exists():s['phase']='paused_boundary';break
            t=tasks[s['cursor']];uid=f'r{t["repeat"]}_{t["arm"]}'
            if js[uid].attempt_count>=30 or sum(j.attempt_count for j in js.values())>=180:raise x.BudgetStop('inherited API budget cap')
            x.execute_task(t,s,p,js[uid],members)
            # Any failed probe triggers the original failure-streak Stop inside
            # execute_task. A complete response resets it without altering policy.
            if s['cursor']%10==0:x.metadata(f'after_{s["cursor"]:03d}',wire.secret)
        else:s['phase']='completed'
        x.write(x.RUN/'checkpoint.json',s);check();x.ledger(s,p);normal=True
    except BaseException as e:
        s['phase']='recovery_stopped';x.write(x.RUN/'checkpoint.json',s)
        x.write(R/'Stop.json',{'error_type':type(e).__name__,'error':str(e)[:1500],'at':x.now(),'automatic_retry':False})
    finally:
        if wire is not None:x.metadata('recovery1_end',wire.secret)
        if keep is not None:
            keep.terminate()
            try:keep.wait(timeout=2)
            except subprocess.TimeoutExpired:keep.kill();keep.wait()
        x.write(R/'End_summary.json',{'phase':s['phase'],'cursor':s['cursor'],'end':x.now(),'lock_retained':not normal,
            'caffeinate_cleaned':keep is not None,'API_summaries':{u:j.summary() for u,j in js.items()} if 'js' in locals() else {}})
        if normal:(x.RUN/'.execution.lock').unlink()


def launch():
    check()
    if any((R/n).exists() for n in ('Launch_identity.json','End_summary.json')):raise ValueError('one-shot probe already launched')
    env={**os.environ,'PYTHONPATH':str(x.ROOT/'code')+':'+str(x.ROOT),'PYTHONDONTWRITEBYTECODE':'1'}
    pid=x.certified.detach([sys.executable,'-B','-c','from '+MODULE+' import run;run()'],R/'Console.log',env=env)
    x.write(R/'Launch_identity.json',{'pid':pid,'at':x.now(),'existing_deadline':x.read(c.C/'Run_clock.json')['deadline']})
    print({'recovery_probe_pid':pid,'remaining_slots_max':8})


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stage',choices=('prepare','check','launch','run'));stage=ap.parse_args().stage
    if stage=='prepare':prepare()
    elif stage=='check':check();print('PASS')
    elif stage=='launch':launch()
    else:run()
