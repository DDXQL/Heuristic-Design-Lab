"""Actual fetched-state import plus bounded synthetic controls. No real API/H/solve/Slurm."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.problems.tsp import eoh_single as native
from heuristic_design.problems import routing_fixtures
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from experiments.triad import stop_recovery as recovery,runtime,shared_admission as shared,parallel,evaluation
from experiments.triad.parallel_tests import fixture as mock_fixture,run_pair,trace,validate_ledger
FETCH=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-native-continuation-20261115/reports/native-continuation-20261115/fetch-1794797115597286000')
OUT=Path(__file__).resolve().parent


def deny(*a,**k):raise AssertionError('OFFLINE: real socket, client dispatch, solver or Slurm prohibited')


def refused(fn):
    try:fn()
    except (PermissionError,ValueError,RuntimeError,FileExistsError,FileNotFoundError):return
    raise AssertionError('required refusal missing')


def sources(parent,pin,p):
    for n,h in p['source_files'].items():assert pin['R9_release']['files'][n]==h
    for n,h in p['source_files'].items():
        if n not in {'experiments/triad/runtime.py','experiments/triad/shared_admission.py','experiments/triad/parallel.py'}:assert sha(ROOT/n)==h,n


def numerical_trace(state,p,d,count,project):
    s=copy.deepcopy(state);a=runtime.Adapter() if project else native.Adapter();records=list(s['tasks'].values());rows=[]
    for i in range(count):
        task={'id':f'SLOT-{state["cursor"]+i:07d}','stage':'new','generation':None,'operator':'adaptive_slot'}
        row,parents=a.task_context(d,s,p,task,state['cursor']+i);assert row and row['operator']!='I1'
        rows.append({'operator':row['operator'],'parents':[r['id'] for r in parents],'np_rng':digest(s['eoh']['np_rng'])})
        pop=native.population(s,p['config']);candidate=next(t for t in records[i%len(records):]+records[:i%len(records)] if t.get('candidate') and t.get('valid'))
        f=native.make_function(candidate['candidate'],task['id'],candidate['fitness'] if i%7 else None);pop.register_function(f);s['eoh']['operator_cursor']+=1;native.save_population(s,pop)
    return rows,s['eoh']


def main():
    pin=read(recovery.PIN);all_before={str(FETCH/item['job_id']/n):h for item in pin['members'] for n,h in item['files'].items()};results={}
    (ROOT/'plans').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='OFFLINE-recovery-',dir=ROOT/'plans') as tmp:
        root=Path(tmp);parent=root/'R9-source';parent.mkdir()
        for n in pin['shared_files']:
            d=parent/n;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(FETCH/'619459'/n,d)
        recovery.PLAN=root/('OFFLINE-recovered-'+str(time.time_ns()));member_root=lambda item:FETCH/item['job_id']
        audit_args={'real_accounting':False,'member_root':member_root,'source_check':sources}
        with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(routing_fixtures,'solve',deny),patch.object(evaluation,'evaluate',deny),patch.object(StrictNonstreamTransport,'dispatch',deny),patch.object(subprocess,'run',deny):
            info=recovery.prepare(parent,**audit_args);manifest=recovery.PLAN/'Shared.json';m=read(manifest)
            assert [r['charged_requests'] for r in info['members']]==[580,587]
            assert [r['remaining_evolution'] for r in info['members']]==[430,423]
            assert [r['next_population_records'] for r in info['members']]==[6,4]
            assert info['shared_charged']==1167 and info['shared_states']['reconciled_failed']==6 and info['shared_states']['completed']==1161
            assert recovery.prepare(parent,**audit_args)['already_prepared']
            rows=[]
            for row,item in zip(m['members'],pin['members']):
                d=Path(row['run_dir']);p,s=runtime.protocol_state(d);old=read(FETCH/item['job_id']/item['run_relative']/'checkpoint.json');oldp=read(FETCH/item['job_id']/item['run_relative']/'Protocol.json')
                assert s['eoh']==old['eoh'] and s['population']==old['population'] and s['cursor']==old['cursor']
                assert sha(d/'Run_clock.json')==old['clock_sha256'] and p['instances']==oldp['instances'] and p['references']==oldp['references'] and p['H_prompt_contract']==oldp['H_prompt_contract'] and p['metrics']==oldp['metrics']
                a,last=numerical_trace(s,p,d,32,True);b,other=numerical_trace(old,oldp,FETCH/item['job_id']/item['run_relative'],32,False)
                assert a==b and last==other
                rows.append({'seed':row['seed'],'next_operator':a[0]['operator'],'next_parents':a[0]['parents'],'32_step_parent_operator_rng_trace_equal_original_native':True,'trace_sha256':digest(a)})
                # Shared STOP must occur BEFORE the next native draw/reservation.
                adapter=shared.adapter(shared.binding(manifest,d,row['config']));copy_s=copy.deepcopy(s);before=digest(copy_s);jhash=sha(d/'API_attempts.json')
                write(recovery.PLAN/'gate/STOP.json',{'OFFLINE_owned_fixture':True})
                task=read(d/'Tasks.json')[s['cursor']];ctx,parents=adapter.task_context(d,copy_s,p,task,s['cursor'])
                assert ctx is None and copy_s['phase']=='paused' and copy_s['eoh']==s['eoh'] and copy_s['tasks']==s['tasks'] and copy_s['cursor']==s['cursor'] and sha(d/'API_attempts.json')==jhash
                (recovery.PLAN/'gate/STOP.json').unlink()  # This OFFLINE fixture only.
                # Descriptor equality uses a dummy env value, never a key file.
                adapter=runtime.Adapter();adapter.check_run(d);bnd=shared.binding(manifest,d,row['config'])
                with patch.dict(os.environ,{p['config']['provider']['api_key_env']:'OFFLINE_NON_SECRET_FIXTURE'}):
                    actual=shared.GuardedTransport(StrictNonstreamTransport(adapter.client_config(p)),shared.Admission(bnd));assert actual.identity==recovery.descriptor(p,bnd)
                j=recovery.journal(adapter,d,s,p,read(d/'Run_clock.json')['deadline'],identity_only=True)
                req=next(iter(j.data['requests'].values()));assert j.request(req['logical_id'],req['prompt'],kind=req['kind'])==req and j.attempt_count==len(old['tasks'])
                # Unknown/tamper remains rejected, without changing source bytes.
                raw=(d/'API_attempts.json').read_bytes();bad=read(d/'API_attempts.json');aid=next(iter(bad['api_attempts']));bad['api_attempts'][aid]['status']='pending';write(d/'API_attempts.json',bad)
                refused(lambda:recovery.inspect());(d/'API_attempts.json').write_bytes(raw)
                raw=(d/'Run_clock.json').read_bytes();clock=read(d/'Run_clock.json');clock['deadline']+=3600;write(d/'Run_clock.json',clock)
                refused(lambda:recovery.inspect());(d/'Run_clock.json').write_bytes(raw)
            raw=(recovery.PLAN/'gate/ledger.json').read_bytes();bad=read(recovery.PLAN/'gate/ledger.json');uid=next(iter(bad['requests']));bad['requests'].pop(uid);write(recovery.PLAN/'gate/ledger.json',bad)
            refused(recovery.inspect);(recovery.PLAN/'gate/ledger.json').write_bytes(raw)
            bad=read(recovery.PLAN/'gate/ledger.json');uid=next(k for k,r in bad['requests'].items() if r['state']=='reconciled_failed');bad['requests'][uid]['state']='completed';write(recovery.PLAN/'gate/ledger.json',bad)
            refused(recovery.inspect);(recovery.PLAN/'gate/ledger.json').write_bytes(raw)
            results['legacy_charge_removal_or_failure_relabelled_success_refused']=True
            results['current_checkpoint_import_and_future_random_plan']=rows
            results['STOP_before_native_draw_request_reservation_and_operator_count']=True
            results['unknown_journal_and_clock_extension_refused']=True
            refused(lambda:recovery.audit(parent,**audit_args,now=1794913156))
            results['expiry_refused_no_implicit_renewal']=True
            # Only fake accounting is queried here. Exact missing/active states fail.
            def fake_account(args,**kw):
                if args[0]=='squeue':return subprocess.CompletedProcess(args,0,stdout='',stderr='')
                return subprocess.CompletedProcess(args,0,stdout=''.join(job+'|'+'|'.join(values)+'|\n' for job,values in pin['accounting'].items()),stderr='')
            with patch.object(subprocess,'run',fake_account):assert recovery.accounting(pin)
            def active_account(args,**kw):return subprocess.CompletedProcess(args,0,stdout='619459|RUNNING\n',stderr='')
            with patch.object(subprocess,'run',active_account):refused(lambda:recovery.accounting(pin))
            results['exact_original_and_U503_terminal_accounting_required']=True
            # All authority writes below are to this temporary OFFLINE account.
            real_load=shared.load;account=root/'OFFLINE-account';account.mkdir();lease=account/'generation.lock'
            def load_fixture(path):
                doc=real_load(path);doc['account_gate']=str(account);return doc
            with patch.object(shared,'load',load_fixture):
                write(lease,{'protocol':'UNKNOWN_OWNER','batch':'OTHER'});bad_hash=sha(lease)
                refused(lambda:recovery.activate(parent,True,**audit_args));assert sha(lease)==bad_hash
                old_identity={'protocol':'SHARED:'+sha(parent/pin['shared_relative']),'batch':str(parent/pin['shared_relative']),'version':'two-independent-searches-prompt-v2-admission-v2'}
                write(lease,old_identity);old_bytes=lease.read_bytes();old_stop=(parent/'plans/native-eoh-501-502/gate/STOP.json').read_bytes();old_ledger=(parent/'plans/native-eoh-501-502/gate/ledger.json').read_bytes()
                assert recovery.activate(parent,True,**audit_args)['activated'] and recovery.activate(parent,True,**audit_args)['already_activated']
                assert (recovery.PLAN/'parent-evidence/account-lease.json').read_bytes()==old_bytes
                assert (parent/'plans/native-eoh-501-502/gate/STOP.json').read_bytes()==old_stop and (parent/'plans/native-eoh-501-502/gate/ledger.json').read_bytes()==old_ledger
                assert read(lease)['protocol']=='SHARED:'+sha(manifest)
                results['owned_atomic_handoff_idempotent_preserves_old_STOP_ledger_and_lease_bytes']=True
                dry=parallel.submit(manifest,'run',False,prefix={0:581,1:588},solve_cap=84)
                assert [x[-3] for x in dry['commands']]==['581','588'] and all(x[-2]=='42' and '--nodelist=node15' in x for x in dry['commands'])
                assert dry['finite_segment_solve_cap']==84
                refused(lambda:recovery.verify_acceptance(manifest,read(recovery.PLAN/'Acceptance.json'),True))
                results['finite_bounds_exactly_one_each_two_requests_84_including_recheck_full_requires_actual_cert']=True
                calls=[]
                def fake_sbatch(args,**kw):
                    assert args[0]=='sbatch';calls.append(args);return subprocess.CompletedProcess(args,0,stdout=str(700100+len(calls))+'\n',stderr='')
                with patch.object(subprocess,'run',fake_sbatch):submitted=recovery.finite_submit(True);again=recovery.finite_submit(True)
                assert submitted['submitted'] and len(submitted['receipts'])==2 and len(calls)==2 and again['already_submitted']
                assert [r['finite_settled_prefix'] for r in submitted['receipts']]==[581,588] and submitted['finite_new_solve_cap']==84
                results['finite_submission_duplicate_operation_does_not_submit_or_spend_again']=True
                first=Path(m['members'][0]['run_dir']);claimfile=next((first/'submissions').glob('*.json'));saved=claimfile.read_bytes();unknown=read(claimfile);unknown['state']='submission_reserved';write(claimfile,unknown)
                with patch.object(subprocess,'run',fake_sbatch):refused(lambda:parallel.submit(manifest,'run',True,2040,True,True,{0:581,1:588},84))
                assert len(calls)==2;claimfile.write_bytes(saved)
                results['unknown_submission_stays_reserved_no_resubmit']=True
        # Existing synthetic production coordinators exercise failed-terminal
        # legacy entries plus safe pause/resume with the new STOP adapter.
        mock=mock_fixture(root,'fjsp-eoh','terminal-failure-coordinators',False);mm=read(mock);g=read(mock.parent/'gate/ledger.json')
        for row in mm['members']:
            for i in range(3):
                uid=digest({'OFFLINE_legacy':row['run_id'],'i':i});g['requests'][uid]={'member':row['run_id'],'key':'OFFLINE-settled-'+str(i),'state':'reconciled_failed','ticket':g['next_ticket'],'charged':True,'outcome':{'classification':'OFFLINE_known_failed'}};g['next_ticket']+=1
        write(mock.parent/'gate/ledger.json',g)
        run_pair(root,mock,['run','run'],[1,6]);clocks=[sha(Path(r['run_dir'])/'Run_clock.json') for r in mm['members']]
        run_pair(root,mock,['resume','run'],[6,6],indices=(0,))
        assert all(read(Path(r['run_dir'])/'checkpoint.json')['phase']=='paused' for r in mm['members']) and not read(mock.parent/'gate/ledger.json')['jobs']
        assert clocks==[sha(Path(r['run_dir'])/'Run_clock.json') for r in mm['members']]
        assert sum(r['state']=='reconciled_failed' for r in read(mock.parent/'gate/ledger.json')['requests'].values())==6
        results['two_actual_local_Mock_coordinators_with_legacy_failed_slots_pause_resume_no_unknown']=True
    assert all(sha(n)==h for n,h in all_before.items())
    assert not subprocess.check_output(['git','diff','923781f','--','code/','experiments/common/run_frozen.py'],cwd=ROOT)
    result={'passed':True,'results':results,'old_bytes_unchanged':True,'public_923781f_unchanged':True,'API_requests':0,'actual_solves':0,'Slurm_submitted':False,'compute_node_verified':False,'finite_actual_requests_authorized_by_test':False}
    write(OUT/'OFFLINE_CHECKS.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
