#!/usr/bin/env python3
"""Two actual local processes and native Mock coordinators; no cluster claim."""
import copy
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from heuristic_design.core import execution,evolution_v1 as frozen
from heuristic_design.llm import routing_transport
from heuristic_design.problems import routing_fixtures
from experiments.triad import runtime,evaluation,entry,parallel,shared_admission as shared

def deny(*a,**k):raise AssertionError('OFFLINE: network, real solver and sbatch forbidden')

def worker(manifest,index,action,prefix,result):
    m=shared.load(manifest);r=m['members'][index];args=parallel.argv(r,action,manifest,prefix)[4:]
    # argv skips python/-s/-B/script; this invokes the production entry directly.
    original=runtime.MockTransport.dispatch;original_eval=runtime.Adapter.evaluate;original_u_eval=frozen.mock_evaluate
    def dispatch(obj,key,prompt,*,kind,on_sent):
        time.sleep(.04);return original(obj,key,prompt,kind=kind,on_sent=on_sent)
    def evaluate(obj,*args):
        started=time.time();time.sleep(.35);value=original_eval(obj,*args)
        with (Path(r['run_dir'])/'OFFLINE_evaluation_timing.jsonl').open('a') as f:f.write(json.dumps({'started':started,'finished':time.time()})+'\n')
        return value
    def u_evaluate(*args):time.sleep(.25);return original_u_eval(*args)
    output=io.StringIO();errors=io.StringIO()
    with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(routing_fixtures,'solve',deny),patch.object(evaluation,'evaluate',deny),patch.object(runtime,'StrictNonstreamTransport',deny),patch.object(routing_transport,'StrictNonstreamTransport',deny),patch.object(runtime.MockTransport,'dispatch',dispatch),patch.object(runtime.Adapter,'evaluate',evaluate),patch.object(frozen,'mock_evaluate',u_evaluate),patch.object(sys,'argv',['entry',*args]),redirect_stdout(output),redirect_stderr(errors):
        try:code=entry.main();write(result,{'code':code,'stderr':errors.getvalue()[-3000:]})
        except BaseException as e:write(result,{'error_type':type(e).__name__,'error':str(e),'stderr':(errors.getvalue()+str(getattr(e,'stderr','')))[-3000:]})

def fixture(root,group,tag,preflight=True):
    source=ROOT/'experiments/triad/recommended.draft'/(group+'.json');c=read(source)
    for key in ('data_manifest','h_file','frozen_u_template','compatible_fixed_results'):
        if c.get(key):c[key]=str((source.parent/c[key]).resolve())
    c.update(mode='mock',freeze_status='engineering_only',repeat_count=2,search_seeds=[502,503],search_seed=None,window_seconds=3600,protocol_receipt='SYNTHETIC_OFFLINE',budget_basis='SYNTHETIC_OFFLINE',account_gate=None,credential_file=None,account_exclusion=None)
    c['resources'].update(cpus=3 if group.endswith('-u') else 2,memory_mib=512,segment_seconds=1800,drain_seconds=1260,partition='OFFLINE',account=None,qos=None)
    if group.endswith('-eoh'):c.update(population_size=2,initialization_request_cap=4,evolution_request_cap=8,api_attempt_cap=12)
    else:
        c['initialization_policy']='bounded_initialization_until_population'
        # One tiny metadata fixture avoids an existing public Mock mean-rounding
        # equality issue at 21 repeated rows; no production validator is changed.
        original=Path(c['data_manifest']);sample=read(original)['instances'][0]
        raw=(original.parent/sample['path']).resolve()
        manifest=root/'synthetic-one.manifest.json'
        write(manifest,{'problem':'fjsp','split':'train','instances':[{'file':raw.name,'path':str(raw),'sha256':sha(raw)}]})
        c.update(data_manifest=str(manifest),instance_count=1)
    cp=root/(tag+'-config.json');write(cp,c)
    spec=root/(tag+'-spec.json');write(spec,{'batch_id':'OFFLINE-shared-'+tag+'-'+str(time.time_ns()),'mode':'mock','min_request_interval_seconds':.05,'queue_wait_seconds':20,'account_gate':str(root/(tag+'-account')),'members':[{'group':group,'seed':seed,'config':str(cp)} for seed in (502,503)]})
    folder=root/(tag+'-plan');out=parallel.plan(spec,folder);p=Path(out['manifest']);m=read(p)
    m['require_initial_preflight']=preflight;write(p,m);shared.activate(p);return p

def run_pair(root,p,actions,prefixes,indices=(0,1)):
    ctx=mp.get_context('spawn');processes=[]
    for i in indices:
        out=root/('result-'+str(time.time_ns())+'-'+str(i)+'.json');proc=ctx.Process(target=worker,args=(str(p),i,actions[i],prefixes[i],str(out)));processes.append((proc,out))
    for proc,out in processes:proc.start()
    for proc,out in processes:
        proc.join(100)
        if proc.is_alive():proc.terminate();proc.join();raise AssertionError('bounded offline worker timeout')
        assert proc.exitcode==0;result=read(out);assert result.get('code')==0,result

def trace(row):
    s=read(Path(row['run_dir'])/'checkpoint.json')
    return {'phase':s['phase'],'population':s['population'],'tasks':[{k:t.get(k) for k in ('id','semantic_id','status','operator','stage','J','fitness','failure','parent_keys','parent_ids','candidate')} for t in s['tasks'].values()],
       'native':{k:s.get('eoh',{}).get(k) for k in ('stage','operator_cursor','initialization_requests','np_rng')},'rng':s.get('rng'),'u_rng':s.get('u_rng')}

def validate_ledger(p):
    m=read(p);s=read(p.parent/'gate/ledger.json');req=list(s['requests'].values());events=s['events'];active=set();peak=0
    for e in events:
        if e['event']=='admitted':active.add(e['uid']);peak=max(peak,len(active))
        elif e['event']=='settled':active.remove(e['uid'])
    assert not active and peak==s['peak']==1 and not s['jobs']
    ordered=[e['uid'] for e in events if e['event']=='admitted'];assert [s['requests'][u]['ticket'] for u in ordered]==sorted(s['requests'][u]['ticket'] for u in ordered)
    sends=sorted(r['sent_at'] for r in req);assert all(b-a>=m['min_request_interval_seconds']-.002 for a,b in zip(sends,sends[1:]))
    assert len(req)<=m['total_request_cap'] and all(sum(v['member']==r['run_id'] for v in req)<=r['request_cap'] for r in m['members'])
    assert {r['member'] for r in req}=={r['run_id'] for r in m['members']}
    overlap=False
    for row in m['members']:
        d=Path(row['run_dir']);timing=d/'OFFLINE_evaluation_timing.jsonl'
        spans=[json.loads(line) for line in timing.read_text().splitlines()] if timing.exists() else [t.get('evaluation_timing',{}) for t in read(d/'checkpoint.json')['tasks'].values()]
        for span in spans:
            for r in req:
                start=span.get('started',span.get('started_at_unix'));end=span.get('finished',span.get('finished_at_unix'))
                if start is not None and end is not None and r['member']!=row['run_id'] and start<=r['sent_at']<=end:overlap=True
    return {'reserved_synthetic_dispatches':len(req),'peak':peak,'FIFO':True,'spacing':True,'per_seed_caps':True,'API_wait_seconds':sum(r['wait_seconds'] for r in req),'peer_request_during_other_evaluation_observed':overlap}

def transport_paths(root):
    # The actual real-mode EoH factory and frozen U routing generate path are
    # exercised with a synthetic wire; no real client, key or socket is used.
    p=fixture(root,'fjsp-eoh','dispatch-path',False);m=read(p);row=m['members'][0];d=Path(row['run_dir']);c=read(row['config']);runtime.prepare(d,row['config'],engineering=True);b=shared.binding(p,d,row['config']);shared.attach(d,b)
    class Wire:
        def __init__(self,c):self.config=c;self.identity='SYNTHETIC_WIRE';self.redact=lambda x:x;self.redact_metadata=lambda x:x
        def preflight(self,prompt):pass
        def dispatch(self,key,prompt,*,kind,on_sent):on_sent();return {'text':'SYNTHETIC_NOT_MODEL','usage':{'input_tokens':0,'output_tokens':0},'metadata':{'http_status':200}}
    with shared.Admission(b).session(d),patch.object(runtime,'StrictNonstreamTransport',Wire):
        a=shared.adapter(b);protocol=read(d/'Protocol.json');protocol['config']['api_mode']='real';wire=a.transport(protocol);wire.dispatch('EOH-real-route','no model',kind='h',on_sent=lambda:None)
        cp=read(d/'checkpoint.json');cp['phase']='paused';write(d/'checkpoint.json',cp)
    with patch.object(routing_transport,'StrictNonstreamTransport',Wire),shared.frozen_hooks(b,d):
        c={**protocol['config'],'api_mode':'real','real_requests_authorized':True}
        result=routing_transport.generate({'request_key':'U-real-route'},'no model',c,10);assert result['sent'] is True
    s=read(p.parent/'gate/ledger.json');assert len(s['requests'])==2 and not s['active'] and s['peak']==1
    return {'real_mode_EoH_transport_factory':True,'unchanged_U_routing_generate_factory':True,'synthetic_dispatches':2,'real_API_requests':0}

def main():
    report=ROOT/'reports/parallel-searches-20261114';report.mkdir(parents=True,exist_ok=True)
    (ROOT/'plans').mkdir(exist_ok=True);results={}
    with tempfile.TemporaryDirectory(prefix='OFFLINE-shared-',dir=ROOT/'plans') as tmp:
        root=Path(tmp)
        for group,prefix in (('fjsp-eoh',8),('fjsp-u',16)):
            p=fixture(root,group,group+'-pair');run_pair(root,p,['run','run'],[prefix,prefix]);m=read(p);pair_traces=[trace(r) for r in m['members']];proof=validate_ledger(p)
            single=fixture(root,group,group+'-alone',False)
            run_pair(root,single,['run','run'],[prefix,prefix],indices=(0,));run_pair(root,single,['run','run'],[prefix,prefix],indices=(1,))
            assert pair_traces==[trace(r) for r in read(single)['members']],group
            assert len({read(Path(r['run_dir'])/'checkpoint.json')['identity'] for r in m['members']})==2
            # One search pauses earlier; peer proceeds. Resume only that member.
            boundary=2 if group.endswith('-u') else 1
            paused=fixture(root,group,group+'-pause');run_pair(root,paused,['run','run'],[boundary,prefix]);pm=read(paused);other=trace(pm['members'][1]);clock=read(Path(pm['members'][0]['run_dir'])/'Run_clock.json')
            run_pair(root,paused,['resume','run'],[prefix,prefix],indices=(0,))
            assert trace(pm['members'][1])==other and read(Path(pm['members'][0]['run_dir'])/'Run_clock.json')==clock
            assert [trace(r) for r in pm['members']]==pair_traces
            assert proof['peer_request_during_other_evaluation_observed'],group
            results[group]={'two_native_coordinators':True,'parallel_matches_alone':True,'independent_protocols_and_directories':True,'single_pause_resume_same_clock_cap_and_trace':True,'safe_initial_boundary':boundary,'Mock_instance_rows':1 if group.endswith('-u') else 21,'peer_continues_and_unchanged_on_other_resume':True,**proof}
        with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny):results['actual_transport_paths']=transport_paths(root)
        # At the exact declared cap, one additional logical key cannot send.
        p=fixture(root,'fjsp-eoh','caps',False);m=read(p);calls=[]
        class Wire:
            config=None;identity='SYNTHETIC_CAP_BOUNDARY'
            def dispatch(self,key,prompt,*,kind,on_sent):calls.append(key);on_sent();return {'text':'SYNTHETIC'}
        for r in m['members']:
            runtime.prepare(r['run_dir'],r['config'],engineering=True);b=shared.binding(p,r['run_dir'],r['config']);shared.attach(r['run_dir'],b)
            cp=read(Path(r['run_dir'])/'checkpoint.json');cp['phase']='paused';write(Path(r['run_dir'])/'checkpoint.json',cp)
            with shared.Admission(b).session(r['run_dir']):
                for i in range(r['request_cap']):shared.GuardedTransport(Wire(),shared.Admission(b)).dispatch(str(i),'fixture',kind='h',on_sent=lambda:None)
        try:shared.Admission(b).acquire('over-cap')
        except RuntimeError:pass
        else:raise AssertionError('member/aggregate cap exceeded')
        assert len(calls)==m['total_request_cap']==len(read(p.parent/'gate/ledger.json')['requests'])
        results['exact_budget_boundary']={'no_extra_dispatch':True,'reserved':len(calls),'refunds':0}
        # Unknown sbatch result: both claims retained, first command called once.
        p=fixture(root,'fjsp-eoh','unknown-submit',False);m=read(p);submitted=[]
        def fake_command(cmd,**kwargs):
            if cmd[0]=='sbatch':submitted.append(cmd);return type('R',(),{'stdout':'UNKNOWN RECEIPT','returncode':0})()
            assert 'prepare' in cmd
            with patch.object(sys,'argv',['entry',*cmd[4:]]),redirect_stdout(io.StringIO()):assert entry.main()==0
            return type('R',(),{'stdout':'{}','returncode':0})()
        with patch.object(parallel.subprocess,'run',fake_command),patch.object(socket.socket,'connect',deny):
            for i in range(2):
                try:parallel.submit(p,'run',send=True,prefix=1,solve_cap=0)
                except (RuntimeError,PermissionError):pass
                else:raise AssertionError('unknown submission repeated/accepted')
        assert len(submitted)==1 and all(list((Path(r['run_dir'])/'submissions').glob('shared-*.json')) for r in m['members'])
        results['unknown_submission']={'synthetic_sbatch_calls':1,'claims_retained':2,'automatic_retry':False,'actual_Slurm_submissions':0}
        # Unknown send: sticky permit and no second member dispatch or retry.
        p=fixture(root,'fjsp-eoh','unknown',False);m=read(p)
        for r in m['members']:
            runtime.prepare(r['run_dir'],r['config'],engineering=True);shared.attach(r['run_dir'],shared.binding(p,r['run_dir'],r['config']))
        r=m['members'][0];b=shared.binding(p,r['run_dir'],r['config'])
        class Unknown:
            config=None;identity='SYNTHETIC_UNKNOWN'
            def dispatch(self,key,prompt,*,kind,on_sent):on_sent();raise TimeoutError('SYNTHETIC response unknown')
        with shared.Admission(b).session(r['run_dir']):
            try:shared.GuardedTransport(Unknown(),shared.Admission(b)).dispatch('never-replay','fixture',kind='h',on_sent=lambda:None)
            except TimeoutError:pass
        s=read(p.parent/'gate/ledger.json');assert len(s['requests'])==1 and len(s['active'])==1 and (p.parent/'gate/STOP.json').exists()
        other=m['members'][1];ob=shared.binding(p,other['run_dir'],other['config'])
        try:
            with shared.Admission(ob).session(other['run_dir']):raise AssertionError('peer admitted after unknown')
        except RuntimeError:pass
        assert len(read(p.parent/'gate/ledger.json')['requests'])==1
        results['unknown']={'shared_STOP':True,'permit_and_budget_retained':True,'no_peer_send_or_replay':True}
    value={'CODE_READY':True,'RUN_READY':False,'scope':'LOCAL TWO PROCESSES AND SYNTHETIC NATIVE COORDINATORS ONLY','API_requests':0,'actual_solves':0,'Slurm_submitted':False,'credential_values_read':0,'actual_cross_job_or_cross_node_verified':False,'results':results}
    write(report/'OFFLINE_CHECKS.json',value);print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
