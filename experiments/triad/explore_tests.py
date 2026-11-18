#!/usr/bin/env python3
"""Targeted synthetic admission/startup/lifecycle checks. No network or solver."""
from contextlib import ExitStack
import copy
import json
import multiprocessing as mp
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from experiments.triad import shared_admission as shared,entry,six_ops,runtime,configuration,evaluation,problems,parallel
from heuristic_design.core import execution


def deny(*a,**kw):raise AssertionError('OFFLINE: real model/network/solver/submission prohibited')
def refused(fn,*a,**kw):
    try:fn(*a,**kw)
    except (PermissionError,ValueError,RuntimeError,FileExistsError,FileNotFoundError,TimeoutError):return
    raise AssertionError('unsafe action accepted')


def fixture(folder,light=True):
    folder=folder.resolve()
    folder.mkdir();path=folder/'Shared.json';rows=[]
    for i,method in enumerate(('u','eoh')):
        rid='OFFLINE-tsp-'+method+'-501';cp=folder/(rid+'.json');d=folder/'runs'/rid
        write(cp,{'mode':'mock','api_attempt_cap':20,'search_seed':501,'group':'tsp-'+method,'shared_manifest':str(path),'provider':{'total_timeout':1},'instance_timeout_seconds':30,'instance_count':20})
        write(d/'checkpoint.json',{'phase':'prepared'})
        rows.append({'group':'tsp-'+method,'seed':501,'index':i,'run_id':rid,'run_dir':str(d),'config':str(cp),'config_sha256':sha(cp),'request_cap':20})
    m={'version':shared.VERSION,'batch_id':'OFFLINE','mode':'mock','members':rows,'max_active_searches':2,'global_API_width':1,
       'total_request_cap':40,'min_request_interval_seconds':0,'queue_wait_seconds':2,'require_initial_preflight':True,
       'account_gate':str(folder/'SYNTHETIC-account'),'account_exclusion':None}
    if light:m['runtime_policy']=shared.EXPLORE
    write(path,m)
    write(Path(m['account_gate'])/'generation.lock',{'protocol':'SHARED:'+sha(path)})
    write(folder/'gate/ledger.json',{'manifest_sha256':sha(path),'requests':{},'active':{},'jobs':{},'next_ticket':0,'events':[],'peak':0,'last_sent_at':0})
    bindings=[{'manifest':str(path),'sha256':sha(path),'run_id':r['run_id']} for r in rows]
    return path,m,bindings


class Inner:
    config=None;identity='SYNTHETIC'
    def __init__(self,kind='ok',counter=None):self.kind=kind;self.calls=0;self.counter=counter
    def dispatch(self,key,prompt,*,kind,on_sent):
        self.calls+=1
        if self.kind!='not_sent':on_sent()
        if self.counter:
            active,peak=self.counter
            with active.get_lock():active.value+=1;peak.value=max(peak.value,active.value)
            time.sleep(.02)
            with active.get_lock():active.value-=1
        if self.kind=='ok':return {'text':'SYNTHETIC','usage':None,'metadata':{}}
        e=TimeoutError('SYNTHETIC failure');e.usage=None
        e.metadata={'send_status':'not_started' if self.kind=='not_sent' else 'unknown' if self.kind=='unknown' else 'confirmed',
                    'failure_stage':'connect' if self.kind=='not_sent' else 'http_receive'}
        if self.kind.startswith('http'):e.metadata['http_status']=int(self.kind[4:])
        raise e


def worker(binding,role,job,counters):
    os.environ['SLURM_JOB_ID']=job
    with patch.object(shared,'verify_attachment',lambda *a:None):
        a=shared.Admission(binding)
        with a.session(Path(a.row['run_dir'])):
            transport=shared.GuardedTransport(Inner(counter=counters),a)
            for i in range(3):transport.dispatch(str(i),'synthetic',kind='h',on_sent=lambda:None)


def main():
    results={};out=ROOT/'reports/explore-runtime-20261118';out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='OFFLINE-explore-') as tmp,ExitStack() as stack:
        tmp=Path(tmp)
        for obj,name in ((socket.socket,'connect'),(socket,'create_connection'),(StrictNonstreamTransport,'__init__'),
                         (problems,'solve_row'),(problems,'solve_obp'),(evaluation,'evaluate')):
            stack.enter_context(patch.object(obj,name,deny))
        stack.enter_context(patch.object(shared,'verify_attachment',lambda *a:None))
        for kind in ('ok','http520','http522','http524','http401','http429','not_sent','unknown'):
            path,m,bs=fixture(tmp/kind);a=shared.Admission(bs[0]);g=path.parent/'gate/ledger.json'
            s=read(g);s['jobs'][a.member]={'token':'synthetic'};write(g,s)
            inner=Inner(kind);t=shared.GuardedTransport(inner,a)
            if kind=='ok':t.dispatch('key','prompt',kind='h',on_sent=lambda:None)
            else:refused(t.dispatch,'key','prompt',kind='h',on_sent=lambda:None)
            s=read(g);r=next(iter(s['requests'].values()));known=kind not in ('unknown',)
            assert len(s['requests'])==1 and inner.calls==1
            assert r['state']==('completed' if kind=='ok' else 'reconciled_failed' if known else 'failed_or_unknown')
            assert bool(s['active'])==(not known)
            assert (path.parent/'gate/STOP.json').exists()==(kind in ('unknown','http401','http429'))
            if known:assert not (path.parent/'gate/send-turn.lock').exists()
            results[kind]={'charged':1,'refund':0,'wire_calls':inner.calls,'state':r['state']}
        path,m,bs=fixture(tmp/'acquire-timeout');a=shared.Admission(bs[0],time.time()-1)
        g=path.parent/'gate/ledger.json';s=read(g);s['jobs'][a.member]={'token':'synthetic'};write(g,s)
        inner=Inner();refused(shared.GuardedTransport(inner,a).dispatch,'key','p',kind='h',on_sent=lambda:None)
        s=read(g);assert inner.calls==0 and next(iter(s['requests'].values()))['state']=='reconciled_failed' and not s['active'] and not (path.parent/'gate/STOP.json').exists()
        results['acquire_reserved_error']={'charged':1,'wire_calls':0,'own_reservation_settled':True}
        path,m,bs=fixture(tmp/'strict',False);a=shared.Admission(bs[0]);g=path.parent/'gate/ledger.json';s=read(g);s['jobs'][a.member]={};write(g,s)
        refused(shared.GuardedTransport(Inner('http524'),a).dispatch,'key','p',kind='h',on_sent=lambda:None)
        assert (path.parent/'gate/STOP.json').exists() and read(g)['active']
        results['strict_policy_preserved']=True
        # A new child still alive after dispatch is not a known terminal release.
        path,m,bs=fixture(tmp/'live-worker');a=shared.Admission(bs[0]);g=path.parent/'gate/ledger.json';s=read(g);s['jobs'][a.member]={};write(g,s)
        with patch.object(shared.multiprocessing,'active_children',side_effect=[[],[SimpleNamespace(pid=999999)]]):
            refused(shared.GuardedTransport(Inner('http524'),a).dispatch,'key','p',kind='h',on_sent=lambda:None)
        assert read(g)['active'] and (path.parent/'gate/STOP.json').exists()
        results['unknown_worker_retained']=True
        # Two local processes exercise the existing fresh-allocation filesystem probe and shared API1.
        path,m,bs=fixture(tmp/'two-process');identity='allocation-OFFLINE-1'
        write(path.parent/'Current_allocation.json',{'identity':identity,'manifest_sha256':sha(path),'state':'submitted','jobs':{m['members'][0]['run_id']:'9001',m['members'][1]['run_id']:'9002'}})
        ctx=mp.get_context('fork');active=ctx.Value('i',0);peak=ctx.Value('i',0)
        ps=[ctx.Process(target=worker,args=(bs[i],i,str(9001+i),(active,peak))) for i in (0,1)]
        for p in ps:p.start()
        for p in ps:p.join(15)
        assert all(not p.is_alive() and p.exitcode==0 for p in ps)
        s=read(path.parent/'gate/ledger.json');assert len(s['requests'])==6 and s['peak']==1 and peak.value==1 and not s['active'] and not s['jobs']
        participants=[read(path.parent/'preflight'/identity/f'participant-{i}.json') for i in (0,1)]
        assert participants[0]['pid']!=participants[1]['pid']
        results['two_processes']={'logical_sends':6,'API_peak':peak.value,'probe_scope':'local OS processes; not Slurm/cross-node acceptance','fresh_job_pid_node_receipts':True}
        with patch.dict(os.environ,{'SLURM_JOB_ID':'9001'}):refused(worker,bs[0],0,'9001',(active,peak))
        assert len(read(path.parent/'gate/ledger.json')['requests'])==6 and (path.parent/'gate/STOP.json').exists()
        results['old_fs_pass_not_reused']=True
        path,m,bs=fixture(tmp/'one-member-resume')
        write(path.parent/'Current_allocation.json',{'identity':'allocation-OFFLINE-single','manifest_sha256':sha(path),'state':'submitted','jobs':{m['members'][0]['run_id']:'9003'}})
        with patch.dict(os.environ,{'SLURM_JOB_ID':'9003'}):worker(bs[0],0,'9003',(active,peak))
        pp=path.parent/'preflight/allocation-OFFLINE-single'
        assert read(pp/'participant-0.json')['pid']!=read(pp/'participant-1.json')['pid']
        assert read(pp/'startup-pass-0.json')['scope']=='one_job_local_probe'
        results['single_member_new_allocation']={'local_helper_only':True,'scope_not_cross_node':True,'new_job_pid_receipt':True}
        # Current owner before secret, exact-own cleanup, and foreign-state preservation.
        c={'mode':'real','account_gate':str(tmp/'inner-gate')};d=tmp/'owned-run';s={'identity':'OFFLINE'}
        write(d/'checkpoint.json',{'phase':'prepared','evaluations':{}})
        with entry.owned_writer(c,d,s):assert read(Path(c['account_gate'])/'generation.lock')['protocol']=='OFFLINE'
        assert not (Path(c['account_gate'])/'generation.lock').exists()
        with entry.owned_writer(c,d,s):write(Path(c['account_gate'])/'generation.lock',{'protocol':'FOREIGN'})
        assert read(Path(c['account_gate'])/'generation.lock')=={'protocol':'FOREIGN'}
        refused(lambda:entry.owned_writer(c,d,s).__enter__())
        credential=tmp/'credential-placeholder';credential.write_text('INERT FIXTURE; NEVER READ');credential.chmod(0o600)
        real={'resources':{'cpus':2,'memory_mib':2048},'credential_file':str(credential)}
        with patch.dict(os.environ,{'SLURM_JOB_ID':'9001','SLURM_CPUS_PER_TASK':'2','SLURM_MEM_PER_NODE':'2G'}):shared.allocation_check(real)
        with patch.dict(os.environ,{'SLURM_JOB_ID':'9001','SLURM_CPUS_PER_TASK':'1','SLURM_MEM_PER_NODE':'2048'}):refused(shared.allocation_check,real)
        results['precredential_checks']={'exact_owner_only_cleanup':True,'foreign_lock_preserved':True,'actual_resource_metadata_checked':True,'credential_value_reads':0}
        path,m,bs=fixture(tmp/'safe-incomplete-close')
        g=path.parent/'gate/ledger.json';state=read(g);state['requests']['unknown']={'member':m['members'][0]['run_id'],'state':'failed_or_unknown'};write(g,state)
        info={'STOP':False,'members':[{'phase':'paused','writer_lock':False},{'phase':'expired','writer_lock':False}]}
        with patch.object(parallel,'inspect',return_value=info),patch.object(sys,'argv',['parallel.py','close','--manifest',str(path)]):
            refused(parallel.main)
            assert (Path(m['account_gate'])/'generation.lock').exists()
            state['requests']['unknown']['state']='reconciled_failed';write(g,state)
            parallel.main()
            assert (path.parent/'Closed.json').exists() and not (Path(m['account_gate'])/'generation.lock').exists()
        results['safe_close']={'paused_expired_not1000_allowed':True,'unknown_request_refused_even_without_STOP':True,'only_owned_account_released':True}
        # Full engine semantic comparison: same tiny synthetic inputs, strict vs new policy.
        manifest=read(ROOT/'preparations/triad/tsp/train20.manifest.json');ref=tmp/'ref.json'
        write(ref,{'kind':'mock-reference-v1','engineering_only':True,'instances':[{'file':x['file'],'reference':1.0} for x in manifest['instances']]})
        runbase=ROOT/'runs';runbase.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='OFFLINE-engine-equivalence-',dir=runbase) as td:
            td=Path(td)
            for method in ('u','eoh'):
                states=[]
                for label in ('strict','explore'):
                    path,m,bindings=fixture(td/(method+'-'+label),label=='explore')
                    role=0 if method=='u' else 1;row=m['members'][role];d=Path(row['run_dir']);cp=Path(row['config'])
                    c=six_ops.config('tsp-'+method);c.update(mode='mock',freeze_status='engineering_only',population_size=3,initialization_request_cap=6,evolution_request_cap=3,api_attempt_cap=9,search_seed=501,reference_file=str(ref),account_gate=str(path.parent/'run-gates'/row['run_id']),account_exclusion=None,credential_file=None,window_seconds=3600,mock_faults={'0':'invalid'},shared_manifest=str(path))
                    write(cp,c);row['config_sha256']=sha(cp);row['request_cap']=9
                    m['total_request_cap']=29;write(path,m)
                    b={**bindings[role],'sha256':sha(path)}
                    write(Path(m['account_gate'])/'generation.lock',{'protocol':'SHARED:'+sha(path)})
                    g=read(path.parent/'gate/ledger.json');g.update(manifest_sha256=sha(path),jobs={row['run_id']:{'token':'SYNTHETIC ENGINE'}});write(path.parent/'gate/ledger.json',g)
                    (d/'checkpoint.json').unlink();d.rmdir();runtime.prepare(d,cp,engineering=True)
                    with patch.object(execution.sys,'platform','linux'):res=execution.start(d,adapter=shared.adapter(b))
                    assert res['phase']=='completed';_,s=runtime.protocol_state(d);states.append(s)
                    assert list(s['tasks'].values())[0]['failure']=='parse_or_constraint_error'
                    assert not (path.parent/'gate/STOP.json').exists()
                semantic=lambda state:[{k:t.get(k) for k in ('semantic_id','operator','parents','parent_keys','candidate','fitness','J','native_population_duplicate','failure')} for t in state['tasks'].values()]
                assert semantic(states[0])==semantic(states[1]) and states[0]['population']==states[1]['population'] and states[0]['u_rng']==states[1]['u_rng']
            # Three known infrastructure failures pause this member; no shared STOP or retries.
            path,m,bindings=fixture(td/'three-known-failures',True);role=1;row=m['members'][role];d=Path(row['run_dir']);cp=Path(row['config'])
            c=six_ops.config('tsp-eoh');c.update(mode='mock',freeze_status='engineering_only',population_size=3,initialization_request_cap=6,evolution_request_cap=3,api_attempt_cap=9,search_seed=501,reference_file=str(ref),account_gate=str(path.parent/'run-gates'/row['run_id']),account_exclusion=None,credential_file=None,window_seconds=3600,mock_faults={},shared_manifest=str(path))
            write(cp,c);row['config_sha256']=sha(cp);row['request_cap']=9;m['total_request_cap']=29;write(path,m);b={**bindings[role],'sha256':sha(path)}
            write(Path(m['account_gate'])/'generation.lock',{'protocol':'SHARED:'+sha(path)})
            g=read(path.parent/'gate/ledger.json');g.update(manifest_sha256=sha(path),jobs={row['run_id']:{'token':'SYNTHETIC'}});write(path.parent/'gate/ledger.json',g)
            (d/'checkpoint.json').unlink();d.rmdir();runtime.prepare(d,cp,engineering=True)
            failing=Inner('http502')
            with patch.object(runtime.MockTransport,'dispatch',side_effect=failing.dispatch),patch.object(execution.sys,'platform','linux'):
                res=execution.start(d,adapter=shared.adapter(b))
            assert res['phase']=='paused' and read(d/'checkpoint.json')['cursor']==3 and failing.calls==3
            g=read(path.parent/'gate/ledger.json');assert len(g['requests'])==3 and not g['active'] and not (path.parent/'gate/STOP.json').exists()
            results['three_failures']={'member_paused_after3':True,'charged3':True,'wire_calls3_no_retries':True,'shared_STOP':False}
        results['search_identity']={'same_mock_sequence_parents_ids_operators_population_J_ties_rng':True,'core_engine_unmodified':True}
    assert not subprocess.check_output(['git','diff','963499d','--','code/','experiments/common','experiments/triad/runtime.py','experiments/triad/evaluation.py'],cwd=ROOT)
    report={'passed':True,'results':results,'API_requests':0,'actual_solves':0,'Slurm_submitted':False,'remote_accesses':0,'R11_changes':0,'scope':'changed-path synthetic checks; no asset reacceptance; no real compute-node claims'}
    write(out/'OFFLINE.json',report);print(json.dumps({'passed':True,'evidence':str(out/'OFFLINE.json'),'API_requests':0,'actual_solves':0,'Slurm_submitted':False}))


if __name__=='__main__':main()
