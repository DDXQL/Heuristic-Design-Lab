#!/usr/bin/env python3
"""Local multi-process synthetic evidence only; no Slurm/cross-node/API claim."""
from pathlib import Path
import copy
import io
import json
import multiprocessing as mp
import os
import socket
import sys
import tempfile
import time
from contextlib import redirect_stdout
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from heuristic_design.core import execution
from heuristic_design.problems import routing_fixtures
from experiments.triad import concurrency_probe as probe,runtime,evaluation,serial_queue,configuration,launch_fjsp,probe_submit


def deny(*a,**kw):raise AssertionError('LOCAL OFFLINE: real network/solver/submission forbidden')


class FakeWire:
    def __init__(self,c):self.config=c;self.identity='SYNTHETIC_NOT_V5_SEND';self.secret='';self.redact=lambda s:s
    def preflight(self,prompt):assert len(prompt)>100
    def dispatch(self,key,prompt,*,kind,on_sent):
        on_sent();time.sleep(.08)
        if os.environ.get('PROBE_FIXTURE_FAIL')=='1':
            e=TimeoutError('SYNTHETIC unknown response');e.metadata={'send_status':'unknown','failure_stage':'response_body'};raise e
        return {'text':'SYNTHETIC RECEIPT; NEVER A MODEL OUTPUT','usage':{'input_tokens':10,'output_tokens':2},'metadata':{'http_status':200,'model':'gpt-6.1-sol','finish_reason':'stop','send_status':'confirmed'}}


def role_fixture(folder,role,fail):
    with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(probe,'StrictNonstreamTransport',FakeWire),patch.dict(os.environ,{'SLURM_JOB_ID':'LOCAL-FIXTURE-'+str(role),'PROBE_FIXTURE_FAIL':'1' if fail and role==0 else '0'}):
        from experiments.triad import entry
        with patch.object(entry,'key',lambda c:None):
            try:probe.worker(folder,role,4)
            except Exception:pass


def pair(root,width,fail=False):
    folder=root/f'pair-{width}-{fail}';folder.mkdir();spec=read(ROOT/'preparations/cluster-concurrency-20261114/phase1/Probe.pending.json');spec.update(phase=width,global_API_width=width,min_request_interval_seconds=0,peer_wait_seconds=10,wall_seconds=400,account_gate=str(folder/'account'))
    # This pair is a local fixture, not a genuine Slurm/phase2 acceptance receipt.
    if width==2:
        first=folder.parent/'phase1';write(first/'PASS.json',{'passed':True,'kind':'SYNTHETIC_LOCAL_ONLY'});spec['phase1_pass_sha256']=sha(first/'PASS.json')
    write(folder/'Probe.json',spec);write(folder/'Approval.json',{'approved_physical_sends':4,'confirm_all_devices_exclusive':True,'probe_sha256':sha(folder/'Probe.json'),'exclusive_until':time.time()+1000})
    for item in spec['prompts']:(folder/item['path']).write_bytes((ROOT/'preparations/cluster-concurrency-20261114/phase1'/item['path']).read_bytes())
    probe.claim(folder/'account/generation.lock',{'protocol':'PROBE:'+sha(folder/'Probe.json')})
    ctx=mp.get_context('spawn');workers=[ctx.Process(target=role_fixture,args=(str(folder),i,fail)) for i in (0,1)]
    for w in workers:w.start()
    for w in workers:w.join(20);assert not w.is_alive();assert w.exitcode==0
    result=probe.collect(folder)
    assert result['global_inflight_peak']<=width and result['reserved_attempts']<=4
    assert result['passed'] is False and not result['independent_Slurm_receipts_verified'] # do not turn fixtures into real cross-job proof
    if not fail:assert result['confirmed_sends']==4 and result['global_inflight_peak']==width and result['HTTP_statuses']==[200]*4
    else:
        assert (folder/'gate/STOP.json').exists() and list((folder/'gate').glob('slot-*.json'))
        gate=probe.Gate(folder/'gate',width,time.time()+.2,0)
        try:gate.acquire('must-not-replay')
        except RuntimeError:pass
        else:raise AssertionError('new allocation after unknown stop')
    return result


def main():
    report=ROOT/'reports/cluster-launch-20261114';report.mkdir(parents=True,exist_ok=True);results={}
    with tempfile.TemporaryDirectory(prefix='cluster-launch-fixture-') as tmp:
        root=Path(tmp).resolve()
        results['local_shared_API1']=pair(root,1);results['local_shared_API2']=pair(root,2);results['local_unknown_stop']=pair(root,1,True)
        # A real coordinator with synthetic receipts, pausing inside initialization.
        c=read(ROOT/'experiments/triad/recommended.draft/fjsp-eoh.json');c.update(mode='mock',freeze_status='engineering_only',population_size=2,initialization_request_cap=4,evolution_request_cap=4,api_attempt_cap=8,repeat_count=1,search_seeds=[7],search_seed=7,window_seconds=3600,protocol_receipt='SYNTHETIC',budget_basis='SYNTHETIC',account_exclusion=None,account_gate=None,credential_file=None)
        for key in ('data_manifest','h_file','frozen_u_template'):
            if c[key]:c[key]=str((ROOT/'experiments/triad/recommended.draft'/c[key]).resolve())
        c['resources'].update(cpus=2,memory_mib=512,segment_seconds=1800,drain_seconds=1000)
        config=root/'finite.json';write(config,c);run=ROOT/'runs'/('cluster-launch-OFFLINE-'+str(time.time_ns()))
        with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(routing_fixtures,'solve',deny),patch.object(evaluation,'evaluate',deny),patch.object(probe.StrictNonstreamTransport,'__init__',deny):
            runtime.prepare(run,config,engineering=True);p,s=runtime.protocol_state(run);write(run/'Current_manual_boundary.json',{'protocol':s['identity'],'original_request_cap':8,'settled_prefix':1})
            out=execution.start(run,adapter=runtime.Adapter());assert out['phase']=='paused';p,s=runtime.protocol_state(run);assert s['cursor']==1;clock=read(run/'Run_clock.json')
            write(run/'Current_manual_boundary.json',{'protocol':s['identity'],'original_request_cap':8,'settled_prefix':None});out=execution.start(run,adapter=runtime.Adapter(),resume=True);assert out['phase']=='completed' and read(run/'Run_clock.json')==clock
        results['finite_native_EoH_prefix']={'passed':True,'first_segment_attempts':1,'first_segment_native_solves':0,'original_cap':8,'clock_unchanged':True,'source':str(run)}
        # Queue never treats exit0/paused as completed; original cap on resume.
        q=root/'queue';rows=[{'run_id':'a','config':'A'},{'run_id':'b','config':'B'}];write(q/'Queue.json',{'rows':rows,'total_original_request_cap':6,'resource_request':{'wall_seconds':100}});write(q/'checkpoint.json',{'phase':'prepared','cursor':0,'total_original_request_cap':6,'history':[]})
        states={'a':{'phase':'prepared'},'b':{'phase':'prepared'}};calls=[]
        def fake_call(cmd,**kw):calls.append(cmd);states[cmd[0]]={'phase':'paused'};return type('R',(),{'returncode':0})()
        with patch.dict(os.environ,{'SLURM_JOB_ID':'LOCAL_QUEUE'}),patch.object(configuration,'load',return_value={'resources':{'drain_seconds':1},'provider':{'total_timeout':1}}),patch.object(serial_queue.batch,'state',lambda r:states[r['run_id']]),patch.object(serial_queue.batch,'command',lambda r,a,real=False:[r['run_id'],a]),patch.object(serial_queue.subprocess,'run',fake_call):
            result=serial_queue.work(q,6);assert result['phase']=='paused' and result['cursor']==0 and len(calls)==1
        assert not serial_queue.can_advance({'phase':'completed','unknown_sends':1}) and not serial_queue.can_advance({'phase':'paused'})
        results['finite_serial_queue']={'passed':True,'exit0_paused_does_not_advance':True,'unknown_completed_does_not_advance':True}
        # An accepted-but-unreadable sbatch receipt is never resent.
        fake_root=root/'submit-fixture';assets=fake_root/'preparations/cluster-concurrency-20261114/phase1';assets.mkdir(parents=True)
        spec=read(ROOT/'preparations/cluster-concurrency-20261114/phase1/Probe.pending.json');spec['account_gate']=str(fake_root/'account');write(assets/'Probe.pending.json',spec)
        for item in spec['prompts']:(assets/item['path']).write_bytes((ROOT/'preparations/cluster-concurrency-20261114/phase1'/item['path']).read_bytes())
        submissions=[]
        def unknown_submit(cmd,**kw):submissions.append(cmd);return type('R',(),{'stdout':'UNKNOWN RECEIPT','returncode':0})()
        with patch.object(probe_submit,'ROOT',fake_root),patch.object(probe_submit,'RUN',fake_root/'runs/probe'),patch.object(probe_submit.subprocess,'run',unknown_submit):
            try:probe_submit.submit(1,4,2,True,True)
            except RuntimeError:pass
            else:raise AssertionError('unknown submission accepted')
            try:probe_submit.submit(1,4,2,True,True)
            except FileExistsError:pass
            else:raise AssertionError('unknown submission replayed')
        assert len(submissions)==1
        results['unknown_sbatch_no_replay']={'passed':True,'synthetic_submission_calls':1,'actual_Slurm_submissions':0}
    proof={'passed':True,'scope':'LOCAL_FILESYSTEM_TWO_PROCESSES_AND_SYNTHETIC_RECEIPTS_ONLY','actual_cross_job_or_cross_node_verified':False,'API_requests':0,'actual_solves':0,'Slurm_submitted':False,'credential_values_read':0,'results':results};write(report/'OFFLINE_CHECKS.json',proof);print(json.dumps({'passed':True,'evidence':str(report/'OFFLINE_CHECKS.json'),'API_requests':0,'actual_solves':0,'cross_node_verified':False},ensure_ascii=False))
if __name__=='__main__':main()
