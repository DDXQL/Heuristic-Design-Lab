"""Finite offline continuation checks: no credentials, H calls, network or sbatch."""
import copy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core import execution
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport,StopAwareJournal
from heuristic_design.problems.tsp import eoh_single as native
from heuristic_design.problems import routing_fixtures
from experiments.triad import native_continuation as nc,runtime,shared_admission as shared,problems,evaluation,parallel
FETCH=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab-triad-concurrent-20261115/reports/concurrent-prompt-v2-20261115/settled-fetch-1794747980856004000')
OUT=Path(__file__).resolve().parent


def deny(*a,**k):raise AssertionError('offline: network/H/real evaluator/submission prohibited')


def refused(fn):
    try:fn()
    except (ValueError,PermissionError,FileExistsError,RuntimeError):return True
    raise AssertionError('required refusal missing')


def fixture(parent,pin):
    for item in pin['members']:
        for n in item['files']:
            d=parent/n;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(FETCH/item['job_id']/n,d)
    for n in pin['shared_files']:
        d=parent/n;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(FETCH/'618885'/n,d)
    for row in read(parent/pin['parent_plan'])['members']:
        item=next(x for x in pin['members'] if x['seed']==row['seed']);p=read(parent/item['run_relative']/'Protocol.json')
        fields=set(read(ROOT/'experiments/triad/configs/fjsp-eoh.json'))|{'shared_manifest'}
        c={k:v for k,v in p['config'].items() if k in fields};c['real_requests_authorized']=False
        path=parent/Path(row['config']).relative_to(pin['parent_root']);write(path,c);assert sha(path)==row['config_sha256']


def trace(state,p,d,count,*,project=True,reload_at=None):
    """Native parent selection/register/survival on recorded data, never execute H."""
    state=copy.deepcopy(state);a=runtime.Adapter() if project else native.Adapter();rows=[]
    stored=list(state['tasks'].values())
    for i in range(count):
        slot={'id':f'SLOT-{10+i:07d}','stage':'new','generation':None,'operator':'adaptive_slot'}
        row,parents=a.task_context(d,state,p,slot,10+i);assert row and row['operator']!='I1'
        rows.append({'operator':row['operator'],'parents':[r['id'] for r in parents],'rng':digest(state['eoh']['np_rng'])})
        # Stored source string and score registration only. Include original ties
        # and invalid records, no new model/program output or evaluation.
        pop=native.population(state,p['config']);record=stored[i%len(stored)]
        candidate=record['candidate'];f=native.make_function(candidate,slot['id'],record['fitness'] if i%7 else None)
        pop.register_function(f);state['eoh']['operator_cursor']+=1;native.save_population(state,pop)
        if reload_at==i:state=json.loads(json.dumps(state))
    return rows,state


def main():
    pin=read(nc.PIN);original={str(FETCH/item['job_id']/n):h for item in pin['members'] for n,h in item['files'].items()}
    stamp=str(time.time_ns());nc.PLAN=ROOT/'plans'/('OFFLINE-native-'+stamp);results={}
    with tempfile.TemporaryDirectory(prefix='settled-parent-offline-') as tmp:
        parent=Path(tmp);fixture(parent,pin)
        with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(routing_fixtures,'solve',deny),patch.object(problems,'solve_row',deny),patch.object(evaluation,'evaluate',deny),patch.object(subprocess,'run',deny):
            info=nc.prepare(parent,accounting=False);m=read(nc.PLAN/'Shared.json')
            results['import']=info
            assert [x['finite_parents'] for x in info['members']]==[8,9] and all(x['charged_requests']==10 and x['cursor']==10 and x['initialization_requests']==10 and x['evolution_attempts']==0 for x in info['members'])
            refused(lambda:nc.prepare(parent,accounting=False))
            refused(lambda:nc.parent_audit(parent,accounting=False,now=1794913156))
            results['duplicate_import_and_expired_deadline_rejected']=True
            traces=[]
            for row in m['members']:
                d=Path(row['run_dir']);p,s=runtime.protocol_state(d);adapter=runtime.Adapter();adapter.check_run(d)
                assert s['eoh']==read(d/'populations/P000_initial.json')
                assert s['phase']=='prepared' and read(d/'parent-evidence/checkpoint.json')['phase']=='initialization_incomplete'
                # Counterfactual uninterrupted native algorithm vs amended adapter.
                t1,last1=trace(s,p,d,64,project=True);t2,last2=trace(s,p,d,64,project=False)
                t3,last3=trace(s,p,d,64,project=True,reload_at=19)
                assert t1==t2==t3 and last1['eoh']==last2['eoh']==last3['eoh']
                assert t1[0]['parents']==p['continuation']['first_E1_parents']
                assert last1['eoh']['initialization_requests']==10
                traces.append({'seed':row['seed'],'first_E1_parents':t1[0]['parents'],'64_operator_parent_rng_steps_equal_native_and_reload':True,'trace_sha256':digest(t1)})
                j=nc.journal(adapter,d,s,p,read(d/'Run_clock.json')['deadline'],identity_only=True)
                old=next(iter(j.data['requests'].values()));assert j.request(old['logical_id'],old['prompt'],kind=old['kind'])==old and j.attempt_count==10
                # An unknown charged request is rejected by the common ledger.
                path=d/'API_attempts.json';raw=path.read_bytes();bad=read(path);key=next(iter(bad['api_attempts']));bad['api_attempts'][key]['status']='pending';write(path,bad)
                refused(lambda:execution.ledger(d,s,p,adapter=adapter));path.write_bytes(raw)
                raw=(d/'Run_clock.json').read_bytes();clock=read(d/'Run_clock.json');clock['deadline']+=1;write(d/'Run_clock.json',clock)
                refused(lambda:adapter.check_run(d));(d/'Run_clock.json').write_bytes(raw)
                # Identity descriptor exactly matches existing constructor with a
                # clearly synthetic key; no credential file is opened.
                b=shared.binding(nc.PLAN/'Shared.json',d,row['config'])
                with patch.dict(os.environ,{p['config']['provider']['api_key_env']:'OFFLINE_NON_SECRET_FIXTURE'},clear=False):
                    inner=StrictNonstreamTransport(adapter.client_config(p));guarded=shared.GuardedTransport(inner,shared.Admission(b))
                    assert guarded.identity==nc.transport_identity(p,b)
                class Synthetic:
                    identity=j.transport.identity
                    def preflight(self,*a):pass
                    def redact(self,s):return s
                    def dispatch(self,key,prompt,*,kind,on_sent):
                        on_sent();return {'text':'OFFLINE ledger fixture, no H','usage':{'input_tokens':0,'output_tokens':0},'metadata':{'mock':True}}
                with tempfile.TemporaryDirectory(prefix='journal-offline-') as jt:
                    sj=StopAwareJournal(Path(jt)/'attempts.json',config=adapter.client_config(p),context=s['identity'],phase=j.phase,transport=Synthetic())
                    sj.data.update(requests=copy.deepcopy(j.data['requests']),api_attempts=copy.deepcopy(j.data['api_attempts']));sj.save()
                    sj.request('SLOT-0000010','OFFLINE ONLY',kind='h');assert sj.attempt_count==11 and sj.calls==11
                    sj.request('SLOT-0000010','OFFLINE ONLY',kind='h');assert sj.attempt_count==11
                    assert sj.policy['api_attempt_cap']==1020 and sj.policy['per_candidate_attempt_cap']==1
                summary=runtime.Adapter().summary(d);assert summary['request_reservations']==10
                assert sum(summary['physical_passes'][x]['completed'] for x in ['first','recheck'])==p['continuation']['imported_solves']
                assert summary['evolution_attempts']==0 and summary['automatic_retries']==0
            results['native_RNG_and_population']=traces
            commands=parallel.submit(nc.PLAN/'Shared.json','run',send=False)
            assert len(commands['commands'])==2 and all('--nodelist=node15' in x and '--cpus-per-task=2' in x and '--mem=2048M' in x and '--no-requeue' in x for x in commands['commands'])
            results['dry_run_submission']=commands
            # Fresh seed503 uses the same policy; no imported population.
            template=read(ROOT/'configurations/triad-adopted-20261115/configs/fjsp-eoh.json')
            assert template['search_seeds']==[501,502,503] and template['initialization_policy']=='native_EoH'
            c=copy.deepcopy(template);c.update(mode='mock',freeze_status='engineering_only',real_requests_authorized=False,search_seed=503,population_size=10,initialization_request_cap=20,evolution_request_cap=12,api_attempt_cap=32,window_seconds=7200,data_manifest=str(ROOT/'preparations/eoh-gap/train21.manifest.json'),account_gate=None,account_exclusion=None,credential_file=None)
            c['resources'].update(segment_seconds=7200)
            config=OUT/('MOCK-'+stamp+'.json');write(config,c)
            full=ROOT/'runs'/('OFFLINE-native-fresh503-'+stamp);runtime.prepare(full,config,engineering=True)
            assert read(full/'checkpoint.json')['population']==[]
            value=execution.start(full,adapter=runtime.Adapter());assert value['phase']=='completed'
            cp=read(full/'checkpoint.json');assert cp['eoh']['initialization_requests']==10 and cp['eoh']['operator_cursor']==12
            c['pause_after_tasks']=11;paused_config=OUT/('MOCK-pause-'+stamp+'.json');write(paused_config,c)
            paused=ROOT/'runs'/('OFFLINE-native-pause503-'+stamp);runtime.prepare(paused,paused_config,engineering=True)
            assert execution.start(paused,adapter=runtime.Adapter())['phase']=='paused'
            clock=sha(paused/'Run_clock.json');assert execution.start(paused,adapter=runtime.Adapter(),resume=True)['phase']=='completed' and sha(paused/'Run_clock.json')==clock
            second=read(paused/'checkpoint.json')
            keys=('operator','parents','candidate','fitness','J','failure','AST_duplicate','native_population_duplicate')
            semantics=lambda s:[{k:t.get(k) for k in keys} for t in s['tasks'].values()]
            assert semantics(cp)==semantics(second) and cp['eoh']==second['eoh']
            runtime.export(full);runtime.export(paused)
            results['mock_full_pause_resume']={'seed':503,'initialization':10,'evolution':12,'native_population':len(cp['eoh']['population']),'finite_parents':len(cp['population']),'same_semantics_and_rng':True,'independent_initialization':True,'program_executions':0,'model_requests':0}
            results['unknown_request_clock_tamper_and_journal_no_replay']=True
            # Real accounting branch with finite synthetic sacct output only.
            def accounting(argv,**kwargs):
                assert argv[0]=='sacct'
                ids=argv[argv.index('-j')+1].split(',')
                return subprocess.CompletedProcess(argv,0,stdout=''.join(job+'|'+('FAILED|2:0' if job in ['618885','618886'] else 'COMPLETED|0:0')+'|\n' for job in ids),stderr='')
            with patch.object(subprocess,'run',accounting):
                nc.parent_audit(parent,accounting=True)
                def unknown(argv,**kwargs):return subprocess.CompletedProcess(argv,0,stdout='',stderr='')
                with patch.object(subprocess,'run',unknown):refused(lambda:nc.parent_audit(parent,accounting=True))
                # Isolate all activation/lease writes in a temporary test gate.
                real_load=shared.load
                fake_account=parent/'OFFLINE-account';fake_account.mkdir()
                def load_fixture(path):
                    value=real_load(path);value['account_gate']=str(fake_account);return value
                write(parent/'plans/first-eoh-501-502/Closed.json',{'manifest_sha256':sha(parent/pin['parent_plan'])})
                with patch.object(shared,'load',load_fixture):
                    lease=fake_account/'generation.lock';write(lease,{'protocol':'OFFLINE_UNKNOWN_OWNER'});before=sha(lease)
                    refused(lambda:nc.activate(parent));assert sha(lease)==before
                    lease.unlink()  # Owned OFFLINE fixture only; never production authority.
                    assert nc.activate(parent)['activated'];refused(lambda:nc.activate(parent))
                    gate_before=read(nc.PLAN/'gate/ledger.json')
                    row=m['members'][0];b=shared.binding(nc.PLAN/'Shared.json',row['run_dir'],row['config']);admission=shared.Admission(b)
                    ledger=read(nc.PLAN/'gate/ledger.json');ledger['jobs'][row['run_id']]={'OFFLINE':True};write(nc.PLAN/'gate/ledger.json',ledger)
                    key='operations/'+read(Path(row['run_dir'])/'parent-evidence/checkpoint.json')['identity']+'/SLOT-0000010/attempt/01'
                    uid=admission.acquire(key);admission.sent(uid);admission.settled(uid,{'usage':{'input_tokens':0,'output_tokens':0}},0)
                    refused(lambda:admission.acquire(key))
                    ledger=read(nc.PLAN/'gate/ledger.json');ledger['jobs']={};write(nc.PLAN/'gate/ledger.json',ledger)
                    assert len(ledger['requests'])==21 and all(ledger['requests'][k]==v for k,v in gate_before['requests'].items())
            results['accounting_unknown_refusal_lease_ownership_one_time_activation_shared_charged20_to21']=True
            # These paths are offline fixtures, not approved executable runs.
            results['scratch_plan']=str(nc.PLAN)
            # Inspect once more while temporary read-only parent fixture exists.
            nc.inspect()
    assert all(sha(p)==h for p,h in original.items())
    public='923781f05686f1899c24fd7899fb3bc6b1df1562'
    changed=subprocess.check_output(['git','diff',public,'--','code/','experiments/common/run_frozen.py'],cwd=ROOT,text=True);assert not changed
    results.update(passed=True,old_evidence_unchanged=True,public_923781f_unchanged=True,real_API_requests=0,actual_solves=0,H_executions=0,Slurm_submitted=False,uploaded=False,new_compute_verification=False,accounting_in_offline_test='not queried; actual sacct terminal check remains mandatory at remote prepare/activate')
    write(OUT/'OFFLINE_CHECKS.json',results);print(json.dumps({'passed':True,'evidence':str(OUT/'OFFLINE_CHECKS.json'),'real_API_requests':0,'actual_solves':0,'uploaded':False},indent=2))

if __name__=='__main__':main()
