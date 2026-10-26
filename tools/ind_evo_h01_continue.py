"""Explicit human-authorized two-hour continuation of the ORIGINAL 11 slots.

Original protocol/clock/end snapshot remain immutable. Mutable search checkpoint,
six request journals and events append in place, retaining their original identity
and all consumed budget. No new sampling or regeneration of failed slots.
"""
from pathlib import Path
import argparse
import json
import os
import signal
import subprocess
import sys

from tools import ind_evo_h01 as x

ROOT=x.ROOT;C=x.RUN/'continuation-v1';MODULE='tools.ind_evo_h01_continue'
EXTRA=('tools/ind_evo_h01_continue.py','tests/test_ind_evo_h01_continue.py')


def prefix_digest(j,initial):
    return x.digest({'requests':{k:j['requests'][k] for k in initial['requests']},
                     'api_attempts':{k:j['api_attempts'][k] for k in initial['api_attempts']}})


def accept():
    import unittest
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_ind_evo_h01_continue')
    with (x.REPORT/'Continuation_offline.log').open('w') as f:r=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    x.write(x.REPORT/'Continuation_offline.json',{'passed':r.wasSuccessful(),'tests':r.testsRun,
        'files':{n:x.sha(ROOT/n) for n in EXTRA},'API':0,'solves':0})
    if not r.wasSuccessful():raise ValueError('continuation offline acceptance')


def prepare():
    if C.exists():raise ValueError('continuation already exists, no reset')
    if (x.RUN/'.execution.lock').exists() or (x.RUN/'Stop.json').exists():raise ValueError('unknown lock/Stop; no cleanup')
    p=x.check();s=x.read(x.RUN/'checkpoint.json');x.ledger(s,p)
    if s['cursor']!=109 or s['phase']!='deadline_partial':raise ValueError('expected authenticated 109 prefix')
    a=x.read(x.REPORT/'Continuation_offline.json')
    if not a['passed'] or any(x.sha(ROOT/n)!=h for n,h in a['files'].items()):raise ValueError('acceptance/source changed')
    C.mkdir();(C/'initial').mkdir()
    files=['checkpoint.json','Run_clock.json','End_summary.json','Events.jsonl']
    files += ['journals/'+f.name for f in sorted((x.RUN/'journals').glob('*.json'))]
    snapshots={}
    for name in files:
        target=C/'initial'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((x.RUN/name).read_bytes())
        snapshots[name]=x.sha(target)
    journals={f.stem:x.read(f) for f in (x.RUN/'journals').glob('*.json')}
    for j in journals.values():
        if any(a['status'] in ('pending','interrupted_unknown') for a in j['api_attempts'].values()):raise ValueError('unknown request state')
    authority={'origin':'direct human answer to current renewal question',
        'human_answer':'授权续跑剩余11个，最长2小时','authorized':True,'scope':'only original Tasks[109:120]',
        'new_launch_seconds':7200,'total_logical_cap':120,'total_API_attempt_cap':180,
        'unit_attempt_cap':30,'candidate_attempt_cap':2,'fees_no_CNY_gate':True,
        'no_seed_reset_no_resampling_no_prior_failed_regeneration':True}
    x.write(C/'Authorization.json',authority)
    binding={'version':'same-plan-continuation-v1','base_protocol_sha256':x.sha(x.RUN/'Protocol.json'),
        'initial_cursor':109,'remaining_tasks':x.read(x.RUN/'Tasks.json')[109:],
        'initial_API_attempts':sum(len(j['api_attempts']) for j in journals.values()),
        'initial_tasks_digest':x.digest(s['tasks']),'snapshots':snapshots,
        'fixed_original_files':{n:x.sha(x.RUN/n) for n in ('Protocol.json','Protocol.sha256','Run_clock.json','End_summary.json')},
        'sources':a['files'],'acceptance_sha256':x.sha(x.REPORT/'Continuation_offline.json'),
        'authority_sha256':x.sha(C/'Authorization.json'),'launch_seconds':7200,'reserve_seconds':1294}
    x.write(C/'Binding.json',binding);(C/'Binding.sha256').write_text(x.sha(C/'Binding.json')+'\n')
    x.write(C/'Controller_expected_identity.json',x.certified.attest_module(MODULE,{'source_files':a['files']}))
    check();print('CONTINUATION_FROZEN',x.sha(C/'Binding.json'))


def check():
    p=x.check();b=x.read(C/'Binding.json')
    if x.sha(C/'Binding.json')!=(C/'Binding.sha256').read_text().strip():raise ValueError('continuation binding identity')
    if b['base_protocol_sha256']!=x.sha(x.RUN/'Protocol.json'):raise ValueError('base scientific protocol changed')
    for name,h in b['fixed_original_files'].items():
        if x.sha(x.RUN/name)!=h:raise ValueError('original clock/protocol/end record changed')
    for name,h in b['snapshots'].items():
        if x.sha(C/'initial'/name)!=h:raise ValueError('initial snapshot changed')
    for name,h in b['sources'].items():
        if x.sha(ROOT/name)!=h:raise ValueError('continuation source changed')
    if x.certified.attest_module(MODULE,{'source_files':b['sources']})!=x.read(C/'Controller_expected_identity.json'):
        raise ValueError('loaded continuation source mismatch')
    if x.sha(C/'Authorization.json')!=b['authority_sha256']:raise ValueError('renewal authority changed')
    s=x.read(x.RUN/'checkpoint.json')
    old=x.read(C/'initial/checkpoint.json')
    if x.digest({k:s['tasks'][k] for k in old['tasks']})!=b['initial_tasks_digest']:raise ValueError('109 original task records changed')
    for f in (C/'initial/journals').glob('*.json'):
        initial=x.read(f);live=x.read(x.RUN/'journals'/f.name)
        if prefix_digest(live,initial)!=prefix_digest(initial,initial):raise ValueError('original API prefix changed')
    return p,b


def run():
    p,b=check()
    if (C/'End_summary.json').exists():return
    if (C/'Stop.json').exists():raise ValueError('persistent continuation Stop')
    fd=os.open(x.RUN/'.execution.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'pid':os.getpid(),'scope':'explicit continuation-v1'},f)
    signal.signal(signal.SIGHUP,signal.SIG_IGN);s=x.read(x.RUN/'checkpoint.json');keep=None;wire=None;normal=False
    try:
        x.ledger(s,p)
        if not (C/'Run_clock.json').exists():
            t=x.now();x.write(C/'Run_clock.json',{'start':t,'deadline':t['wall']+7200,'authority_sha256':b['authority_sha256']})
        clock=x.read(C/'Run_clock.json')
        if clock['deadline']!=clock['start']['wall']+7200:raise ValueError('renewal time budget changed')
        s['continuation']={'binding_sha256':x.sha(C/'Binding.json'),'clock_sha256':x.sha(C/'Run_clock.json'),
                           'authority_sha256':b['authority_sha256']}
        x.write(x.RUN/'checkpoint.json',s)
        keep=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        from fjsp_usage.research_real.leafapi import load_local_key
        os.environ['LEAFAPI_API_KEY']=load_local_key(ROOT.parent/'FJSP-Heuristic-Research/.env.leafapi.local')
        wire=x.WireRecorder(x.JsonCandidateTransport(x.config(p)),x.RUN/'wire_responses',verify=check)
        transport=x.Transport(wire,clock['deadline'])
        journals={u:x.AttemptJournal(x.RUN/'journals'/(u+'.json'),config=x.config(p),context=x.sha(x.RUN/'Protocol.json'),
            phase=x.NAME+'/'+u,transport=transport) for u in s['units']}
        x.metadata('continuation1_start',wire.secret)
        members=tuple(x.checked_candidate(m['candidate'],'h') for m in x.read(x.RUN/'H_frozen.json')['members'])
        tasks=x.read(x.RUN/'Tasks.json');x.event('continuation_started',new_deadline=clock['deadline'],cursor=s['cursor'])
        while s['cursor']<120:
            check();x.ledger(s,p)
            if x.time.time()+b['reserve_seconds']>clock['deadline']:s['phase']='continuation_deadline_partial';break
            if (x.RUN/'Pause_request.json').exists():s['phase']='paused_boundary';break
            task=tasks[s['cursor']];uid=f'r{task["repeat"]}_{task["arm"]}'
            if journals[uid].attempt_count>=30:raise x.BudgetStop('inherited per-search API cap')
            if sum(j.attempt_count for j in journals.values())>=180:raise x.BudgetStop('inherited total API cap')
            x.execute_task(task,s,p,journals[uid],members)
            if s['cursor']%10==0:x.metadata(f'after_{s["cursor"]:03d}',wire.secret)
        else:s['phase']='completed'
        x.write(x.RUN/'checkpoint.json',s);check();x.ledger(s,p);normal=True
    except BaseException as e:
        s['phase']='continuation_stopped';x.write(x.RUN/'checkpoint.json',s)
        x.write(C/'Stop.json',{'error_type':type(e).__name__,'error':str(e)[:1500],'at':x.now(),'automatic_retry':False})
    finally:
        if wire is not None:x.metadata('continuation1_end',wire.secret)
        if keep is not None:
            keep.terminate()
            try:keep.wait(timeout=2)
            except subprocess.TimeoutExpired:keep.kill();keep.wait()
        x.write(C/'End_summary.json',{'phase':s['phase'],'cursor':s['cursor'],'end':x.now(),
            'lock_retained':not normal,'caffeinate_cleaned':keep is not None,
            'API_summaries':{u:j.summary() for u,j in journals.items()} if 'journals' in locals() else {}})
        if normal:(x.RUN/'.execution.lock').unlink()


def launch():
    check()
    if any((C/n).exists() for n in ('Launch_identity.json','Run_clock.json','End_summary.json')):raise ValueError('continuation already started; no implicit replay')
    env={**os.environ,'PYTHONPATH':str(ROOT/'code')+':'+str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'}
    pid=x.certified.detach([sys.executable,'-B','-c','from '+MODULE+' import run;run()'],C/'Console.log',env=env)
    x.write(C/'Launch_identity.json',{'pid':pid,'at':x.now(),'method':'same verified detached session/files/SIGHUP ignore'})
    print({'launched':pid,'remaining':11})


def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=('accept','prepare','check','launch','run'));stage=a.parse_args().stage
    if stage=='accept':accept()
    elif stage=='prepare':prepare()
    elif stage=='check':check();print('PASS')
    elif stage=='launch':launch()
    else:run()


if __name__=='__main__':main()
