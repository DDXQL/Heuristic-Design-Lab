"""Final offline evidence audit; no solve/generation functions called."""
from datetime import datetime
import hashlib
import subprocess
from zoneinfo import ZoneInfo

from tools import h01_external_confirm as c
from tools import h01_external_data as d


def main():
    p=c.check();s=c.read(c.RUN/'checkpoint.json');c.ledger(s,p)
    assert s['phase']=='completed' and s['cursor']==len(c.read(c.RUN/'Tasks.json'))==40
    manifest=c.read(c.RUN/'Data_manifest.json');legacy=c.read(c.ROOT/'data/fjsp_manifest.json')
    assert len(manifest['instances'])==20 and manifest['instances']==d.select(manifest['candidate_pool'])
    assert all(r['sha256']==legacy['files'][r['file']]['sha256'] for r in manifest['legacy_content_comparisons'])
    payload_checks=[];pids=[];max_gap=0.
    for task in c.read(c.RUN/'Tasks.json'):
        t=s['tasks'][task['task_id']];spec=p['instances'][task['instance_index']]
        folder=(c.RUN/t['result_path']).parent;r=c.read(folder/'result.json');raw=c.read(folder/'raw_result.json')
        assert {k:v for k,v in r.items() if k!='boundary'}==raw
        payload=c.read(folder/'Input_receipt.json');policy=p['policies'][task['policy']]
        assert payload['candidate']==policy and payload['instance']==spec and payload['H_order']==p['H_order']
        assert payload['protocol_sha256']==c.sha(c.RUN/'Protocol.json')
        assert r['valid'] and len(r['instances'])==1 and r['total_instances']==1
        row=r['instances'][0];assert row['file']==spec['file'] and row['captured_solves']==2
        assert row['physical_schedule_sha256']==row['recheck_physical_schedule_sha256']
        assert row['single_h_calls']==row['recheck_h_calls'] and not any(row['network_guard'].values())
        life=c.read(folder/'lifecycle.json');pids.append(life['pid'])
        assert life['alive'] is False and life['exitcode']==0 and life['all_results_received']
        assert life['receiver_thread_stopped'] and all(a['timely'] for a in life['instance_receives'])
        assert c.read(folder/'before.json')['identity']==c.read(folder/'after.json')['identity']==c.read(c.RUN/'Expected_solver_identity.json')['identity']
        assert r['boundary']['decision']=='accepted' and not (folder/'Clock_quarantine.json').exists()
        gap=(t['finished']['wall']-t['started']['wall'])-(t['finished']['monotonic']-t['started']['monotonic'])
        assert abs(gap)<=2;max_gap=max(max_gap,abs(gap))
        payload_checks.append({'task_id':task['task_id'],'U_code_sha256':hashlib.sha256(policy['code'].encode()).hexdigest(),
            'candidate_key':policy['key'],'instance_sha256':spec['sha256'],'result_sha256':t['result_sha256'],
            'normal_exit0':True,'two_passes_equal':True})
    clock=c.read(c.RUN/'Run_clock.json');end=c.read(c.RUN/'End_summary.json');controller=c.read(c.RUN/'Run_identity.json')['pid']
    assert clock['deadline']==clock['start']['wall']+43200 and end['cursor']==40 and end['caffeinate_cleaned']
    assert all(t['started']['wall']+90<=clock['deadline'] for t in s['tasks'].values())
    ps=subprocess.check_output(['ps','-axo','pid=,ppid=,comm=,args='],text=True)
    alive=[];awake=[]
    for line in ps.splitlines():
        values=line.strip().split(None,3)
        if len(values)!=4:continue
        pid=int(values[0]);comm,args=values[2:]
        if pid in set(pids+[controller]):alive.append({'pid':pid,'comm':comm})
        if comm.endswith('caffeinate') and f'-w {controller}' in args:awake.append(pid)
    assert not alive and not awake and not (c.RUN/'.execution.lock').exists()
    archive=c.read(c.REPORT/'Raw_manifest.json')
    assert c.sha(c.REPORT/'Raw_evidence.tar.gz')==archive['archive_sha256']
    assert all(c.sha(c.ROOT/n)==r['sha256'] for n,r in archive['files'].items())
    old_manifest=c.read(c.old.REPORT/'Raw_primary_manifest.json')
    assert all(c.sha(c.ROOT/n)==r['sha256'] for n,r in old_manifest['files'].items())
    at=datetime.now(ZoneInfo('Asia/Manila')).isoformat()
    c.write(c.REPORT/'Final_verification.json',{'passed':True,'at_manila':at,'new_API':0,'new_solves_during_audit':0,
        'certified_program_instances':40,'certified_first_recheck_passes':80,'unknown_requests_or_tasks':0,
        'source_txt_json_and_conversion_equality':True,'old60_hashes_match_original_manifest':True,
        'policy_identity':{k:{'AST_key':v['key'],'UTF8_code_sha256':hashlib.sha256(v['code'].encode()).hexdigest()} for k,v in p['policies'].items()},
        'tasks':payload_checks,'max_task_wall_monotonic_gap_seconds':max_gap,
        'controller_pid_ended':controller,'worker_pids_ended':len(pids),'campaign_caffeinate_ended':True,'signals_sent':0,
        'start_manila':datetime.fromtimestamp(clock['start']['wall'],ZoneInfo('Asia/Manila')).isoformat(),
        'end_manila':datetime.fromtimestamp(end['end']['wall'],ZoneInfo('Asia/Manila')).isoformat(),
        'deadline_manila':datetime.fromtimestamp(clock['deadline'],ZoneInfo('Asia/Manila')).isoformat(),
        'campaign_elapsed_wall_seconds':end['end']['wall']-clock['start']['wall'],
        'old_IND_EVO_primary_files_unchanged':len(old_manifest['files']),'frozen_execution_source_unchanged':True,
        'archive_matches_current_raw_files':True,'protocol_sha256':c.sha(c.RUN/'Protocol.json')})
    print('PASS: 40 certified items/80 passes; identities, archive, old history and process cleanup verified; audit solves/API=0')


if __name__=='__main__':main()
