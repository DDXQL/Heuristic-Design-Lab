"""Explain cost phases from saved records only; does not run schedules."""
import csv
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
RUN=ROOT/'runs'/OUT.name
BASE=ROOT/'runs/tier2-baseline-a-train21-seed501-20261024-v1'


def read(path):return json.loads(path.read_text())


def main():
    protocol=read(RUN/'Protocol.json')
    assert hashlib.sha256((BASE/'checkpoint.json').read_bytes()).hexdigest()==protocol['protected_files'][str((BASE/'checkpoint.json').relative_to(ROOT))]
    original=read(BASE/'checkpoint.json');rows=[]
    for id,entry in original['strategies'].items():
        result=read(BASE/entry['result_path'])
        if result['valid']:continue
        name=result['failed_instance'];stem=Path(name).stem;folder=RUN/'evidence'/id
        new=read(folder/'result.json');row=next((r for r in new['instances'] if r['file']==name),None)
        progress=read(folder/(stem+'.progress.json')) if (folder/(stem+'.progress.json')).exists() else {}
        life=read(folder/'lifecycle.json');receive=next((r for r in life['instance_receives'] if r['file']==name),{})
        first=row['single_solve_seconds'] if row else None;second=row['deterministic_recheck_seconds'] if row else None
        wait=(receive['finished']-receive['started']) if receive.get('timely') else None
        rows.append({'strategy':id,'old_failed_instance':name,'old_full_fitness':None,'new_strategy_valid':new['valid'],
            'new_instance_complete':row is not None,'new_first_seconds':first,'new_recheck_seconds':second,
            'new_two_solve_seconds':first+second if row else None,
            'new_parent_complete_wait_seconds':wait,'new_wait_exceeds_15_diagnostic_only':wait>15 if wait is not None else None,
            'new_post_recheck_until_send_end_seconds':progress['send_end']-progress['recheck_end'] if progress.get('send_end') else None,
            'new_final_after_identity_seconds':progress['after_identity_end']-progress['after_identity_start'] if 'after_identity_end' in progress else None,
            'old_parent_poll_timeout_seconds':result['parent_observed_instance_seconds']})
    with (OUT/'Former_timeout_phase_diagnostics.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    call_rows=[]
    for id in read(RUN/'checkpoint.json')['strategies']:
        result=read(RUN/'evidence'/id/'result.json')
        for r in result['instances']:
            call_rows.append({'strategy':id,'file':r['file'],'first_total_H_calls':sum(r['single_h_calls']),
                'recheck_total_H_calls':sum(r['recheck_h_calls']),
                **{f'first_H{i}_calls':n for i,n in enumerate(r['single_h_calls'])}})
    with (OUT/'Member_calls_189.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(call_rows[0]),lineterminator='\n');w.writeheader();w.writerows(call_rows)
    with (OUT/'Composite_pair_instances_945.csv').open() as f:all_static=list(csv.DictReader(f))
    for i in range(10):
        id=f'H{i}';entry=original['strategies'][id];path=BASE/entry['result_path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['result_sha256']
        result=read(path);assert result['valid'] and len(result['instances'])==21
        for r in result['instances']:
            all_static.append({'strategy':id,'source':'Baseline-A-original','strategy_valid':True,'file':r['file'],
                'Cmax':r['makespan'],'LB':r['lower_bound'],'score':r['score'],'row_status':'complete'})
    assert len(all_static)==1155
    with (OUT/'Composite_static_instances_1155.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(all_static[0]),lineterminator='\n');w.writeheader();w.writerows(all_static)
    print(json.dumps({'records':len(rows),'scope':'Saved T30 trace phases; not a new T15 run or retrospective acceptance of old nulls.'},ensure_ascii=False))


if __name__=='__main__':main()
