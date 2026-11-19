#!/usr/bin/env python3
"""Focused synthetic tests; no credentials, network, real solver or Slurm."""
import ast
import copy
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from experiments.triad import time_continuation as tc,shared_admission as shared,configuration,parallel
from experiments.triad.explore_tests import fixture,Inner,refused


def deny(*a,**kw):raise AssertionError('OFFLINE: network/submission/solver/credential prohibited')


def continuation_fixture(folder):
    path,m,bindings=fixture(folder);accounting={}
    for i,row in enumerate(m['members']):
        d=Path(row['run_dir']);c=read(row['config'])
        c.update(problem='tsp',method=('u' if i==0 else 'eoh'),window_seconds=480,
            evolution_request_cap=10,account_gate=str(path.parent/'run-gates'/row['run_id']),
            resources={'segment_seconds':120,'drain_seconds':20},
            account_exclusion={'scope':'all_devices_sharing_account','confirmation':True,'valid_until':600})
        write(row['config'],c);row['config_sha256']=sha(row['config'])
        clock={'start':0,'deadline':480};write(d/'Run_clock.json',clock)
        a={'id':f'key-{i}','status':'completed','send_confirmed':True,'usage':{'input_tokens':3,'output_tokens':2}}
        write(d/'API_attempts.json',{'api_attempts':{a['id']:a},'halt_reason':None})
        cp={'phase':'paused','pause_reason':tc.TIME_PAUSE,'clock_sha256':sha(d/'Run_clock.json'),
            'cursor':1,'eoh':{'initialization_requests':0,'operator_cursor':1}}
        write(d/'checkpoint.json',cp)
        receipt={'state':'submitted','job_id':str(9001+i),'finite_settled_prefix':None}
        write(d/'submissions/shared-resume-original.json',receipt);write(d/'latest-submission.json',receipt)
        accounting[receipt['job_id']]={'state':'COMPLETED','exit_code':'0:0'}
    write(path,m);write(Path(m['account_gate'])/'generation.lock',{'protocol':'SHARED:'+sha(path)})
    state=read(path.parent/'gate/ledger.json');state['manifest_sha256']=sha(path)
    for i,row in enumerate(m['members']):
        key=f'key-{i}';state['requests'][digest({'member':row['run_id'],'key':key})]={'member':row['run_id'],'key':key,'state':'completed'}
    write(path.parent/'gate/ledger.json',state)
    return path,m,accounting


def tree_bytes(folder):
    return {str(p.relative_to(folder)):p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def main():
    results={}
    with tempfile.TemporaryDirectory(prefix='HDL-time-OFFLINE-') as tmp:
        tmp=Path(tmp)
        with patch.object(socket,'create_connection',deny),patch.object(socket.socket,'connect',deny),patch.object(subprocess,'run',deny),\
             patch.object(configuration,'load',side_effect=lambda p,**kw:read(p)),\
             patch.object(tc,'check_run',side_effect=lambda row,*a:read(Path(row['run_dir'])/'checkpoint.json')):
            path,m,ac=continuation_fixture(tmp/'readonly');before=tree_bytes(path.parent)
            info=tc.inspect(path,accounting=ac,now=100);assert info['eligible'] and info['selected']==[0,1]
            assert tree_bytes(path.parent)==before
            assert not tc.inspect(path,now=100)['eligible']
            results['readonly_no_scheduler_assumption']={'eligible_only_with_exact_accounting':True,'run_bytes_unchanged':True}
            cases={
                'stop':lambda p,m,a:write(p.parent/'gate/STOP.json',{'reason':'synthetic'}),
                'writer':lambda p,m,a:write(Path(m['members'][0]['run_dir'])/'.execution.lock',{'pid':1}),
                'unknown_submission':lambda p,m,a:write(Path(m['members'][0]['run_dir'])/'submissions/shared-unknown.json',{'state':'submission_reserved'}),
                'unknown_wire':lambda p,m,a:mutate(p.parent/'gate/ledger.json',lambda x:x['requests'][next(iter(x['requests']))].update(state='failed_or_unknown')),
                'active_search':lambda p,m,a:mutate(p.parent/'gate/ledger.json',lambda x:x['jobs'].update({'foreign':{}})),
                'wrong_owner':lambda p,m,a:write(Path(m['account_gate'])/'generation.lock',{'protocol':'FOREIGN'}),
                'manual_pause':lambda p,m,a:mutate(Path(m['members'][0]['run_dir'])/'checkpoint.json',lambda x:x.update(pause_reason='user_control')),
                'API_pause':lambda p,m,a:mutate(Path(m['members'][0]['run_dir'])/'checkpoint.json',lambda x:x.update(pause_reason='three consecutive failed transports; resume requires user action')),
                'finite_prefix':lambda p,m,a:mutate(Path(m['members'][0]['run_dir'])/'latest-submission.json',lambda x:x.update(finite_settled_prefix=1)),
                'scheduler_failed':lambda p,m,a:a['9001'].update(state='FAILED',exit_code='2:0'),
                'scheduler_running':lambda p,m,a:a['9001'].update(state='RUNNING'),
                'clock_changed':lambda p,m,a:mutate(Path(m['members'][0]['run_dir'])/'Run_clock.json',lambda x:x.update(deadline=999)),
            }
            for name,change in cases.items():
                p,mm,a=continuation_fixture(tmp/name);change(p,mm,a)
                assert not tc.inspect(p,accounting=a,now=100)['eligible'],name
            assert not tc.inspect(path,accounting=ac,now=361)['eligible']
            c=read(m['members'][0]['config']);clock=read(Path(m['members'][0]['run_dir'])/'Run_clock.json')
            refused(tc.check_calendar,c,clock,470,full_segment=False)
            refused(tc.check_calendar,c,clock,float('nan'),full_segment=False)
            results['guard_refusals']=list(cases)+['insufficient_full_segment','insufficient_precredential_drain','nonfinite_clock']
            # Only future exploration manifests may be used; R13/strict refuses.
            p,mm,a=continuation_fixture(tmp/'strict');mm.pop('runtime_policy');write(p,mm)
            refused(tc.inspect,p,accounting=a,now=100)
            results['R13_strict_not_migrated']=True
            # The synthetic controller calls the existing submit function twice,
            # never an API or a new runner. Original cap and action are unchanged.
            p,mm,a=continuation_fixture(tmp/'bounded');infos=[{'eligible':True,'blockers':[],'selected':[0,1]}]*3
            receipts={'receipts':[{'job_id':'9001'},{'job_id':'9002'}]}
            with patch.object(tc,'inspect',side_effect=copy.deepcopy(infos)),patch.object(tc,'accounting_for',return_value=a),patch.object(parallel,'submit',return_value=receipts) as submit:
                out=tc.bounded(p,max_segments=2,max_seconds=60,approved=40,allow_api=True,allow_solves=True,poll_seconds=1)
                assert out['submitted_segments']==2 and submit.call_count==2
                assert all(call.args[1]=='resume' and call.kwargs['approved']==40 and call.kwargs['member'] is None for call in submit.call_args_list)
            refused(tc.bounded,p,max_segments=3,max_seconds=60,approved=40,allow_api=True,allow_solves=True)
            with patch.object(tc,'inspect',return_value={'eligible':True,'blockers':[],'selected':[0,1]}),patch.object(tc,'accounting_for',return_value=a),patch.object(parallel,'submit',deny):
                refused(tc.bounded,p,max_segments=1,max_seconds=60,approved=40,allow_api=True,allow_solves=True)
            results['bounded_existing_submit_reused']={'maximum_segments':2,'maximum_jobs':4,'no_budget_increase':True,'same_authorization_not_replayed':True}
            p,mm,a=continuation_fixture(tmp/'one-member')
            with patch.object(tc,'inspect',return_value={'eligible':True,'blockers':[],'selected':[1]}),patch.object(tc,'accounting_for',return_value=a),patch.object(parallel,'submit',return_value=receipts) as submit:
                tc.bounded(p,max_segments=1,max_seconds=60,approved=40,allow_api=True,allow_solves=True)
                assert submit.call_count==1 and submit.call_args.kwargs['member']==1
            results['one_remaining_member_only']=True
            p,mm,a=continuation_fixture(tmp/'unknown-submit')
            with patch.object(tc,'inspect',return_value={'eligible':True,'blockers':[],'selected':[0,1]}),patch.object(tc,'accounting_for',return_value=a),patch.object(parallel,'submit',side_effect=RuntimeError('unknown sbatch')) as submit:
                refused(tc.bounded,p,max_segments=2,max_seconds=60,approved=40,allow_api=True,allow_solves=True)
                assert submit.call_count==1 and (p.parent/'time-continuation/controller.lock').exists()
                assert (p.parent/'time-continuation/decision-01.json').exists() and not (p.parent/'time-continuation/decision-02.json').exists()
            results['unknown_submit_not_replayed']=True
        # Exercise the actual admission failure classifier, not a mocked decision.
        with patch.object(shared,'verify_attachment',lambda *a:None):
            for http in (520,522,524):
                for known_usage in (False,True):
                    path,m,bs=fixture(tmp/f'HTTP-{http}-{known_usage}');a=shared.Admission(bs[0]);g=path.parent/'gate/ledger.json'
                    state=read(g);state['jobs'][a.member]={};write(g,state)
                    inner=Inner('http'+str(http),usage_known=known_usage)
                    refused(shared.GuardedTransport(inner,a).dispatch,'key','prompt',kind='h',on_sent=lambda:None)
                    state=read(g);r=next(iter(state['requests'].values()))
                    assert inner.calls==1 and len(state['requests'])==1
                    assert r['state']==('reconciled_failed' if known_usage else 'failed_or_unknown')
                    assert bool(state['active'])==(not known_usage)
                    assert (path.parent/'gate/STOP.json').exists()==(not known_usage)
            results['HTTP_status_not_usage_proof']={'statuses':[520,522,524],'unknown_usage_retained':True,'known_usage_one_failed_charge_no_retry':True}
        # The new calendar check must precede key(), owned writer and execution.
        tree=ast.parse((ROOT/'experiments/triad/entry.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        calls={}
        for n in ast.walk(main):
            if isinstance(n,ast.Call):
                name=n.func.id if isinstance(n.func,ast.Name) else ''
                if name in ('check_calendar','owned_writer','key'):calls.setdefault(name,[]).append(n.lineno)
        assert min(calls['check_calendar'])<min(calls['owned_writer'])<min(calls['key'])
        results['precredential_calendar_order']={'AST_verified':True,'real_credential_reads':0}
    report={'passed':True,'scope':'synthetic local continuation and failure guards; no real Slurm/requeue acceptance',
        'results':results,'API_requests':0,'actual_solves':0,'Slurm_submissions':0,'SSH_attempts':0}
    print(json.dumps(report,ensure_ascii=False,indent=2))


def mutate(path,fn):
    value=read(path);fn(value);write(path,value)


if __name__=='__main__':main()
