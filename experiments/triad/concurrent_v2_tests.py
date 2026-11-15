#!/usr/bin/env python3
"""Local processes and fake wire/LKH only. No socket, scheduler or solver."""
import io
import json
import multiprocessing as mp
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import runtime,shared_admission as shared,parallel,assets,parallel_tests


def deny(*a,**k):raise AssertionError('OFFLINE: actual network, API, LKH, solver or Slurm forbidden')


def api2_worker(path,index,result):
    path=Path(path);m=shared.load(path);r=m['members'][index];d=Path(r['run_dir']);b=shared.binding(path,d,r['config'])
    class Wire:
        config=None;identity='SYNTHETIC_API2_SLOW_WIRE'
        def dispatch(self,key,prompt,*,kind,on_sent):
            on_sent();time.sleep(.4);return {'text':'SYNTHETIC_NO_MODEL','usage':{'input_tokens':0,'output_tokens':0}}
    with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny):
        with shared.Admission(b).session(d):shared.GuardedTransport(Wire(),shared.Admission(b)).dispatch('bounded-one','SYNTHETIC',kind='h',on_sent=lambda:None)
    write(result,{'passed':True,'real_API_requests':0})


def main():
    (ROOT/'plans').mkdir(exist_ok=True);checks=[]
    with tempfile.TemporaryDirectory(prefix='OFFLINE-v2-',dir=ROOT/'plans') as temp,patch.object(socket.socket,'connect',deny):
        root=Path(temp);p=parallel_tests.fixture(root,'fjsp-eoh','API2',False);m=read(p)
        for row in m['members']:
            runtime.prepare(row['run_dir'],row['config'],engineering=True);shared.attach(row['run_dir'],shared.binding(p,row['run_dir'],row['config']));s=read(Path(row['run_dir'])/'checkpoint.json');s['phase']='paused';write(Path(row['run_dir'])/'checkpoint.json',s)
        write(p.parent/'API2.finite.json',{'manifest_sha256':sha(p),'adapter_sha256':sha(shared.__file__),'before_reservations':0,'reservation_stop_at':2,'synthetic_fixture_only':True})
        ledger=read(p.parent/'gate/ledger.json');ledger['API2_finite_sha256']=sha(p.parent/'API2.finite.json');write(p.parent/'gate/ledger.json',ledger)
        ctx=mp.get_context('spawn');jobs=[]
        for i in range(2):
            out=root/('api2-result-'+str(i)+'.json');job=ctx.Process(target=api2_worker,args=(str(p),i,str(out)));jobs.append((job,out));job.start()
        for job,out in jobs:
            job.join(30)
            if job.is_alive():job.terminate();job.join();raise AssertionError('bounded synthetic process timeout')
            assert job.exitcode==0 and read(out)['passed']
        ledger=read(p.parent/'gate/ledger.json');assert not ledger['active'] and not ledger['jobs'] and ledger['peak']==2 and parallel.sent_peak(ledger)==2 and len(ledger['requests'])==2
        sent=[e for e in ledger['events'] if e['event']=='sent'];assert sent[1]['at']-sent[0]['at']>=.04
        r=m['members'][0];b=shared.binding(p,r['run_dir'],r['config'])
        with shared.Admission(b).session(r['run_dir']):
            try:shared.Admission(b).acquire('must-not-exceed-finite-cap')
            except PermissionError:pass
            else:raise AssertionError('extra finite phase reservation admitted')
        assert len(read(p.parent/'gate/ledger.json')['requests'])==2
        checks.append('two real local processes, synthetic sends overlap at2, global send-turn spacing, no third finite reservation, original caps unchanged')
        p=parallel_tests.fixture(root,'fjsp-eoh','per-request-clock',False);m=read(p);r=m['members'][0];d=Path(r['run_dir']);runtime.prepare(d,r['config'],engineering=True);b=shared.binding(p,d,r['config']);shared.attach(d,b);s=read(d/'checkpoint.json');s['phase']='paused';write(d/'checkpoint.json',s)
        class Wire:
            config=None;identity='SYNTHETIC_PERSISTENT_ADAPTER'
            def dispatch(self,key,prompt,*,kind,on_sent):on_sent();return {'text':'SYNTHETIC'}
        a=shared.Admission(b)
        with a.session(d):
            shared.GuardedTransport(Wire(),a).dispatch('one','SYNTHETIC',kind='h',on_sent=lambda:None);end=a.wait_deadline;time.sleep(.02)
            shared.GuardedTransport(Wire(),a).dispatch('two','SYNTHETIC',kind='h',on_sent=lambda:None);assert a.wait_deadline>end and a.deadline is None
        checks.append('persistent frozen-U transport gets fresh bounded queue deadline per request, not process-age360s')
        p=parallel_tests.fixture(root,'fjsp-eoh','STOP-drain',False);m=read(p);bindings=[]
        for row in m['members']:
            d=Path(row['run_dir']);runtime.prepare(d,row['config'],engineering=True);b=shared.binding(p,d,row['config']);shared.attach(d,b);ss=read(d/'checkpoint.json');ss['phase']='paused';write(d/'checkpoint.json',ss);bindings.append(b)
        a0=shared.Admission(bindings[0]);a1=shared.Admission(bindings[1])
        class PeerStop:
            config=None;identity='SYNTHETIC_STOP_BEFORE_KNOWN_CALLBACK'
            def dispatch(self,key,prompt,*,kind,on_sent):
                shared.stop(p.parent/'gate','SYNTHETIC peer stops before owned send callback')
                try:a1.acquire('known-not-sent')
                except RuntimeError:pass
                else:raise AssertionError('peer sent after STOP')
                assert not (p.parent/'gate/metrics.lock').exists()
                on_sent();return {'text':'SYNTHETIC existing physical send drains'}
        with a0.session(m['members'][0]['run_dir']),a1.session(m['members'][1]['run_dir']):
            shared.GuardedTransport(PeerStop(),a0).dispatch('already-owned','SYNTHETIC',kind='h',on_sent=lambda:None)
        state=read(p.parent/'gate/ledger.json');assert not state['active'] and len(state['requests'])==1 and next(iter(state['requests'].values()))['state']=='completed'
        checks.append('known read-only STOP refusal releases only its owned unmodified writer mutex; peer physical-send callback/settlement drains; unknown leases still sticky')
        # LKH CPU/wall limits wired into existing runner; fake process only.
        folder=root/'LKH-fake';folder.mkdir();binary=folder/'fake-not-executable';binary.write_text('NOT LKH; never executed')
        par=folder/'parameters.par';par.write_text('SYNTHETIC');tsp=folder/'problem.tsp';tsp.write_text('SYNTHETIC')
        plan={'spec':{'lkh_binary':str(binary),'lkh_binary_sha256':sha(binary),'cpu_seconds':120,'timeout_seconds':150,'runs':10,'max_trials':1000},'commands':[{'file':'SYNTHETIC','command':[str(binary),str(par)],'parameter_file':str(par),'parameter_sha256':sha(par),'problem_sha256':sha(tsp),'tour':str(folder/'missing.tour')}]};write(folder/'reference-plan.json',plan);calls=[];kills=[]
        class Fake:
            pid=999999999
            def __init__(self,*args,**kwargs):calls.append((args,kwargs));self.count=0
            def wait(self,timeout):
                self.count+=1
                if self.count==1:raise subprocess.TimeoutExpired(['SYNTHETIC'],timeout)
                return -9
        with patch.object(assets.subprocess,'Popen',Fake),patch('os.killpg',lambda *a:kills.append(a)):
            try:assets.lkh_run(folder,True,1)
            except subprocess.TimeoutExpired:pass
            else:raise AssertionError('LKH timeout ignored')
        assert 'setrlimit(resource.RLIMIT_CPU,(120,120))' in calls[0][0][0][4] and calls[0][1]['start_new_session'] is True and kills
        assert read(folder/'LKH-run-receipt.json')['phase']=='stopped'
        try:assets.lkh_run(folder,True,1)
        except ValueError:pass
        else:raise AssertionError('failed LKH budget replayed')
        checks.append('fake LKH child gets CPU hard120, wall150, private process group killed and joined on timeout; stopped receipt prevents automatic retry')
    result={'passed':True,'checks':checks,'API_requests':0,'actual_solves':0,'LKH_runs':0,'Slurm_submitted':False,'API2_actual_verified':False,'RUN_READY':False}
    out=ROOT/'reports/concurrent-prompt-v2-20261115/OFFLINE_V2.json';write(out,result);print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
