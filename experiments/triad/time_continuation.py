#!/usr/bin/env python3
"""Opt-in bounded continuation of clean time pauses; reuse parallel.submit.

Default inspection has no subprocess, credentials, or state writes. This is a
foreground client, not a search engine or Slurm requeue implementation. It is
only for future freezes containing this module, never the live frozen R13.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core import execution
from experiments.triad import candidate_policy,configuration,parallel,shared_admission as shared
from experiments.triad.concurrency_probe import claim

TIME_PAUSE='segment drain before next reservation'
TERMINAL={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}


class AccountingPending(PermissionError):
    """Slurm may release dependencies before the accounting row is visible."""


def check_calendar(c,clock,now,*,full_segment):
    values=[now,clock.get('start'),clock.get('deadline'),c.get('window_seconds')]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        raise PermissionError('finite original clock required')
    if clock['deadline']!=clock['start']+c['window_seconds'] or clock['start']>now:
        raise PermissionError('original clock changed or local clock moved backwards')
    r=c['resources'];segment=r['segment_seconds'];drain=r['drain_seconds']
    if type(segment) is not int or type(drain) is not int or not 0<drain<segment:
        raise PermissionError('original segment/drain required')
    if now+(segment if full_segment else drain)>=clock['deadline']:
        raise PermissionError('original window cannot cover requested segment' if full_segment else 'original window cannot cover next drain')
    if r.get('independent_batch'):return
    e=c.get('account_exclusion') or {}
    until=e.get('valid_until')
    if (e.get('scope')!='all_devices_sharing_account' or not e.get('confirmation') or
        type(until) not in (int,float) or not math.isfinite(until) or until<clock['deadline']):
        raise PermissionError('unchanged all-device exclusion must cover original deadline')


def accounting_for(m):
    if not shared.exploration(m):raise PermissionError('future exploration freeze only; no scheduler call for R13')
    ids=set()
    for row in m['members']:
        for f in (Path(row['run_dir'])/'submissions').glob('shared-*.json'):
            r=read(f)
            if r.get('state')!='submitted' or not str(r.get('job_id','')).isdigit():
                raise PermissionError('unknown submission retained; no automatic resend')
            ids.add(r['job_id'])
    if not ids:raise PermissionError('original submitted segments required')
    result=subprocess.run(['sacct','-n','-P','-j',','.join(sorted(ids)),
        '--format=JobIDRaw,State,ExitCode'],check=True,text=True,capture_output=True,timeout=30)
    found={}
    for line in result.stdout.splitlines():
        cols=line.split('|')
        if len(cols)>=3 and cols[0] in ids:
            if cols[0] in found:raise PermissionError('ambiguous accounting rows; no automatic continuation')
            found[cols[0]]={'state':cols[1].split()[0],'exit_code':cols[2]}
    if set(found)!=ids:raise AccountingPending('accounting missing exact job IDs')
    return found


def check_run(row,path,c):
    d=Path(row['run_dir']);binding=shared.binding(path,d,row['config'])
    adapter=shared.adapter(binding);p=adapter.check_run(d);s=read(d/'checkpoint.json')
    execution.ledger(d,s,p,adapter=adapter)
    return s


def inspect_independent(path,m,accounting,now,operator_resume):
    rows=[];selected=[];blockers=[]
    owner=Path(m['account_gate'])/'generation.lock'
    if (path.parent/'Closed.json').exists() or not owner.exists() or read(owner).get('protocol')!='SHARED:'+sha(path):
        blockers.append('batch owner missing or already closed')
    if accounting is None:blockers.append('Slurm terminal accounting is required')
    for row in m['members']:
        d=Path(row['run_dir']);config=read(row['config']);target=config['evolution_request_cap']
        saved={};detail=None
        try:
            saved=read(d/'checkpoint.json')
            latest=read(d/'latest-submission.json')
            previous=(accounting or {}).get(latest.get('job_id'),{})
            if previous.get('state') not in TERMINAL:
                blockers.append(row['run_id']+': previous worker Slurm terminal state unknown')
                raise ValueError('previous worker Slurm terminal state unknown')
            saved=check_run(row,path,config)
            if any((d/n).exists() for n in ('.execution.lock','.coordinator.lock','Stop.json','Clock_quarantine.json')) or (Path(config['account_gate'])/'generation.lock').exists():
                raise ValueError('local worker state requires review')
            phase=saved['phase'];reason=saved.get('pause_reason')
            if phase=='paused' and (reason==candidate_policy.TIME_PAUSE or reason=='user_control' and operator_resume):
                if previous!={'state':'COMPLETED','exit_code':'0:0'}:
                    raise ValueError('last worker did not exit cleanly')
                check_calendar(config,read(d/'Run_clock.json'),now,full_segment=False)
                j=read(d/'API_attempts.json')
                spent=candidate_policy.costs(j)['reservations_by_stage'].get('evolution',0)
                if spent>=m['candidate_policy']['evolution_attempt_cap']:
                    raise ValueError(candidate_policy.BUDGET_PAUSE)
                if saved.get('successful_evolution_responses',0)!=sum(t.get('successful_evolution_response',False) for t in saved['tasks'].values()):
                    raise ValueError('checkpoint counter mismatch')
                selected.append(row['index'])
            elif phase not in ('completed','initialization_incomplete','expired','paused'):
                detail='worker ended without a resumable checkpoint'
        except (OSError,ValueError,KeyError,TypeError) as error:
            detail=str(error)
        progress=saved.get('successful_evolution_responses',0)
        rows.append({'index':row['index'],'run_id':row['run_id'],'phase':saved.get('phase','unavailable'),
                     'pause_reason':saved.get('pause_reason'),'successful_evolution_responses':progress,
                     'remaining_evolution':max(0,target-progress),'detail':detail})
    return {'members':rows,'selected':selected,'eligible':bool(selected) and not blockers,'blockers':blockers,
            'scientific_complete':not blockers and all(r['phase']=='completed' and r['remaining_evolution']==0
                                                       and r['detail'] is None for r in rows)}


def inspect(path,*,accounting=None,now=None,operator_resume=False):
    """Read-only assessment. Missing scheduler facts never become permission."""
    now=time.time() if now is None else now;path=Path(path).resolve();m=shared.load(path)
    if not shared.exploration(m):raise PermissionError('future exploration freeze only; never migrate R13/strict runs')
    if shared.independent(m):return inspect_independent(path,m,accounting,now,operator_resume)
    policy=m.get('candidate_policy');blockers=[];members=[];selected=[]
    for f in ('Closed.json','gate/STOP.json','gate/metrics.lock','gate/send-turn.lock'):
        if (path.parent/f).exists():blockers.append('retained '+f)
    gate=Path(m['account_gate'])/'generation.lock'
    if not gate.exists() or read(gate).get('protocol')!='SHARED:'+sha(path):blockers.append('whole-account ownership missing/different')
    state=read(path.parent/'gate/ledger.json')
    if state.get('manifest_sha256')!=sha(path):blockers.append('shared ledger binding differs')
    if state['active'] or state['jobs']:blockers.append('active/unknown account or search reservation')
    if any(r['state'] not in ('completed','reconciled_failed') for r in state['requests'].values()):blockers.append('unsettled shared request retained')
    if accounting is None:blockers.append('exact Slurm accounting not inspected')
    for row in m['members']:
        d=Path(row['run_dir']);c=configuration.load(row['config'],engineering=m['mode']=='mock')
        # Frozen FJSP U uses another coordinator. Do not infer its time-pause
        # semantics from this triad adapter or bypass its own validation.
        if c['problem']=='fjsp' and c['method']=='u':
            raise PermissionError('frozen FJSP U automatic continuation not implemented')
        s=check_run(row,path,c);v=s['eoh'];clock=read(d/'Run_clock.json')
        if s.get('clock_sha256')!=sha(d/'Run_clock.json'):blockers.append(row['run_id']+': original clock binding differs')
        evo=v['operator_cursor'];progress=s.get('successful_evolution_responses',0) if policy else evo
        complete=s['phase']=='completed' and progress==c['evolution_request_cap']
        reason=s.get('pause_reason');local_terminal=bool(policy and (
            s['phase'] in ('initialization_incomplete','expired')
            or s['phase']=='paused' and reason in (candidate_policy.BUDGET_PAUSE,candidate_policy.STREAK_PAUSE)))
        window_closed=False
        if not complete and not local_terminal:
            try:check_calendar(c,clock,now,full_segment=not policy)
            except PermissionError as e:
                if policy and str(e)=='original window cannot cover next drain':window_closed=True
                else:blockers.append(row['run_id']+': '+str(e))
        names=('.execution.lock','.coordinator.lock','Stop.json','Clock_quarantine.json')
        if any((d/n).exists() for n in names) or (Path(c['account_gate'])/'generation.lock').exists():blockers.append(row['run_id']+': writer/stop/quarantine retained')
        j=read(d/'API_attempts.json');attempts=j['api_attempts']
        if j.get('halt_reason') or any(a['status'] not in ('completed','failed') for a in attempts.values()):blockers.append(row['run_id']+': local API halt/unknown retained')
        logical_count=len(j['requests']) if policy else len(attempts)
        if len(attempts)>row['request_cap'] or logical_count!=s['cursor'] or s['cursor']!=v['initialization_requests']+v['operator_cursor']:
            blockers.append(row['run_id']+': original attempt accounting differs')
        if policy:
            reservations=candidate_policy.costs(j)['reservations_by_stage']
            if (reservations.get('initialization',0)>c['initialization_request_cap']
                    or reservations.get('evolution',0)>policy['evolution_attempt_cap']
                    or progress!=sum(t.get('successful_evolution_response',False) for t in s['tasks'].values())):
                blockers.append(row['run_id']+': successful-response or phase cap mismatch')
        for a in attempts.values():
            record=state['requests'].get(digest({'member':row['run_id'],'key':a['id']}),{})
            if record.get('member')!=row['run_id'] or record.get('key')!=a['id'] or record.get('state') not in ('completed','reconciled_failed'):
                blockers.append(row['run_id']+': local/shared request settlement differs');break
        receipts=[]
        for f in (d/'submissions').glob('shared-*.json'):
            r=read(f);receipts.append(r)
            a=(accounting or {}).get(r.get('job_id'),{})
            if r.get('state')!='submitted' or (accounting is not None and a.get('state') not in TERMINAL):blockers.append(row['run_id']+': prior submission active/unknown')
        latest=read(d/'latest-submission.json');a=(accounting or {}).get(latest.get('job_id'),{})
        if latest not in receipts:blockers.append(row['run_id']+': latest receipt not in durable submissions')
        wanted_state,wanted_exit=('FAILED','2:0') if policy and s['phase'] in ('initialization_incomplete','expired') else ('COMPLETED','0:0')
        if accounting is not None and (a.get('state')!=wanted_state or a.get('exit_code')!=wanted_exit):
            blockers.append(row['run_id']+': last Slurm segment not clean COMPLETED 0:0')
        if not complete and not local_terminal:
            allowed_pauses={candidate_policy.TIME_PAUSE if policy else TIME_PAUSE}
            if policy and operator_resume:allowed_pauses.add('user_control')
            if policy and s['phase']=='paused' and reason=='user_control' and not operator_resume:
                pass  # A user hold is settled but must not resume automatically.
            elif s['phase']!='paused' or reason not in allowed_pauses or latest.get('finite_settled_prefix') is not None:
                blockers.append(row['run_id']+': not an unrestricted clean time pause')
            elif progress>=c['evolution_request_cap'] or len(attempts)>=row['request_cap']:
                blockers.append(row['run_id']+': original budget exhausted')
            elif not window_closed:selected.append(row['index'])
        members.append({'index':row['index'],'run_id':row['run_id'],'phase':s['phase'],
            'evolution_attempts':evo,'successful_evolution_responses':progress if policy else None,
            'remaining_evolution':max(0,c['evolution_request_cap']-progress),
            'pause_reason':reason,'local_terminal':local_terminal,'window_closed':window_closed,
            'charged_requests':len(attempts),'original_request_cap':row['request_cap'],
            'deadline':clock['deadline'],'checkpoint_sha256':sha(d/'checkpoint.json')})
    if len(state['requests'])>m['total_request_cap']:blockers.append('aggregate original cap exceeded')
    return {'sampled_at':now,'manifest_sha256':sha(path),'members':members,'selected':selected,
        'eligible':bool(selected) and not blockers,'blockers':blockers,'scientific_complete':all(r['phase']=='completed' and r['remaining_evolution']==0 for r in members),
        'original_aggregate_cap':m['total_request_cap'],'API_requests_by_inspection':0,'actual_solves_by_inspection':0,
        'native_requeue_verified':False,'credential_reads':0}


def bounded(path,*,max_segments,max_seconds,approved,allow_api,allow_solves,poll_seconds=30):
    """Explicit future authorization only. Every submit goes through old guards.

    A crash/unknown decision retains this controller claim. Starting the client
    again cannot replay a submission. No automatic failure repair or account
    release exists here.
    """
    path=Path(path).resolve();m=shared.load(path)
    if (type(max_segments) is not int or not 1<=max_segments<=2 or type(max_seconds) is not int or
        not 1<=max_seconds<=172800 or not 1<=poll_seconds<=60 or approved!=m['total_request_cap'] or not allow_api or not allow_solves):
        raise PermissionError('explicit original aggregate cap/API/solves and 1..2 bounded segments required')
    first=inspect(path,accounting=accounting_for(m))
    if not first['eligible']:raise PermissionError('not eligible: '+ '; '.join(first['blockers']))
    folder=path.parent/'time-continuation';lock=folder/'controller.lock'
    if (folder/'Authorization.json').exists():raise PermissionError('bounded authorization already consumed; no replay')
    owner={'pid':os.getpid(),'token':str(time.time_ns()),'manifest_sha256':sha(path)}
    claim(lock,owner)
    claim(folder/'Authorization.json',{**owner,'maximum_new_segments':max_segments,'maximum_new_jobs':2*max_segments,
        'maximum_controller_seconds':max_seconds,'original_aggregate_cap':approved,'new_API_budget':0,
        'no_retry_or_refund':True,'at':time.time(),'source_sha256':sha(__file__)})
    end=time.monotonic()+max_seconds;submitted=0;last=first
    try:
        for number in range(1,max_segments+1):
            last=inspect(path,accounting=accounting_for(m))
            if not last['eligible']:break
            if time.monotonic()>=end:break
            if not lock.exists() or read(lock)!=owner:raise PermissionError('controller owner changed; no submit')
            # The durable decision consumes one segment even if the sbatch
            # response becomes unknown. It must never be replayed.
            claim(folder/f'decision-{number:02d}.json',{'before':last,'state':'submission_reserved','at':time.time()})
            chosen=last['selected'];member=None if len(chosen)==2 else chosen[0]
            receipt=parallel.submit(path,'resume',send=True,approved=approved,allow_api=True,allow_solves=True,member=member)
            submitted+=1;write(folder/f'receipt-{number:02d}.json',receipt)
            # The last authorized segment continues without this client. Earlier
            # ones are polled read-only; any non-clean result ends the chain.
            if number==max_segments:break
            ids=[r['job_id'] for r in receipt['receipts']]
            while time.monotonic()<end:
                ac=accounting_for(m)
                if all(ac[j]['state'] in TERMINAL for j in ids):break
                time.sleep(min(poll_seconds,max(0,end-time.monotonic())))
            else:break
        result={'submitted_segments':submitted,'maximum_segments':max_segments,'original_aggregate_cap':approved,
            'last_assessment':last,'automatic_failure_retry':False,'new_API_budget':0,'account_released':False}
        write(folder/'End.json',result)
        if lock.exists() and read(lock)==owner:lock.unlink()
        return result
    except BaseException as e:
        write(folder/'Halt.json',{'error_type':type(e).__name__,'error':str(e),'owner_retained':True,'automatic_retry':False})
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['check-only','resume-time'],nargs='?',default='check-only')
    p.add_argument('--manifest',required=True,type=Path);p.add_argument('--read-accounting',action='store_true')
    for f in ('submit','allow-api','allow-solves'):p.add_argument('--'+f,action='store_true')
    p.add_argument('--approve-requests',type=int);p.add_argument('--max-segments',type=int);p.add_argument('--max-controller-seconds',type=int)
    a=p.parse_args()
    if a.action=='check-only':
        if a.submit or a.allow_api or a.allow_solves or a.approve_requests is not None:raise PermissionError('inspection is not execution approval')
        value=inspect(a.manifest,accounting=accounting_for(shared.load(a.manifest)) if a.read_accounting else None)
    else:
        if not a.submit or not a.read_accounting:raise PermissionError('manual submit and exact accounting required')
        value=bounded(a.manifest,max_segments=a.max_segments,max_seconds=a.max_controller_seconds,
            approved=a.approve_requests,allow_api=a.allow_api,allow_solves=a.allow_solves)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False}),file=sys.stderr);raise SystemExit(2)
