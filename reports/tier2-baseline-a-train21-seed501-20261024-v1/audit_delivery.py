"""Independent persisted-data delivery audit. No scheduler/model invocation."""
import csv
import tempfile
from statistics import fmean
from tools import tier2_baseline_a as b
from tools.baseline_a_audit import extract
from fjsp_usage.baseline_a.validation import validate_result,validate_ledger
from fjsp_usage.research.events import atomic_json

p=b.check(b.DEFAULT);out=b.REPORT;s=b.v2.read(out/'Summary.json');state=b.v2.read(b.DEFAULT/'checkpoint.json')
assert state['phase']=='completed' and len(state['strategies'])==55
reserved=validate_ledger(state,p,b.v2.read,b.v2.sha,b.DEFAULT)
assert reserved==861
results={};normal=0;timeouts=0;call_costs=[]
expected=b.v2.read(b.DEFAULT/'Expected_loaded_identity.json')['identity']
for identifier,record in state['strategies'].items():
    result=b.v2.read(b.DEFAULT/record['result_path']);results[identifier]=result
    assert b.v2.sha(out/'certified_results'/(identifier+'.json'))==record['result_sha256']
    if result['valid']:
        assert len(result['instances'])==21
        assert result['fitness']==fmean(-r['makespan']/r['lower_bound'] for r in result['instances'])
    else:assert result['fitness'] is None
    for row in result['instances']:
        first=row.get('single_h_calls');second=row.get('recheck_h_calls',row.get('deterministic_recheck_h_calls'))
        call_costs.append({'strategy':identifier,'origin':record['origin'],'file':row['file'],
            'complete_strategy_valid':result['valid'],'first_H_calls':sum(first) if first is not None else None,
            'recheck_H_calls':sum(second) if second is not None else None,
            'CPU_seconds':row.get('instance_CPU_seconds'),'peak_RSS_bytes_macos':row.get('peak_RSS_bytes_macos'),
            'cost_scope':'certified complete instance pair; failed/unreached instances excluded, unknown not zero'})
    if identifier in p['cache']:
        cache=p['cache'][identifier]
        assert result==extract(b.v2.read(b.ROOT/cache['source_file']),cache['selector'])
    else:
        folder=b.DEFAULT/'evidence'/identifier
        before=b.v2.read(folder/'before.json');life=b.v2.read(folder/'lifecycle.json');boundary=b.v2.read(folder/'boundary.json')
        assert before['identity']==b.digest(before['modules'])==expected and life['pid']==before['pid'] and life['alive'] is False
        end=b.v2.read(folder/'after.json') if (folder/'after.json').exists() else None
        files={**p['source_files'],**p['protected_files']};actual={n:b.v2.sha(b.ROOT/n) for n in files}
        certified=b.classify(result,before=before,after=end,lifecycle=life,expected_identity=expected,
            expected_files=files,start_files=actual,end_files=actual,worker_failure=(folder/'worker_failure.json').exists())
        assert certified['decision']==boundary['decision']!='stop'
        if result['valid']:
            normal+=1;assert life['exitcode']==0 and life['trigger'] is None
            assert b.v2.read(folder/'after.json')['identity']==expected
            assert life['cleanup']==['join_exit_grace_2.0'] and life['rows_received']==21
        else:
            timeouts+=1;assert boundary['decision']=='candidate_invalid_continue'
            assert result['error_type']=='Timeout' and life['trigger']=='parent_poll_timeout'
            assert life['exitcode'] in (-15,-9) and life['exit_grace_used'] is False

with (out/'All_instances_1155.csv').open() as f:rows=list(csv.DictReader(f))
assert len(rows)==1155 and len({(r['strategy'],r['file']) for r in rows})==1155
assert all(r['Cmax']==r['score']=='' for r in rows if r['status'] in ('failed','not_reached'))
oracle=b.v2.read(out/'Oracle.json');oracle_scores=[];oracle_Cmax=[]
for j,expected_instance in enumerate(p['instances']):
    makespan=min(results[f'H{i}']['instances'][j]['makespan'] for i in range(10))
    oracle_Cmax.append(makespan);oracle_scores.append(-makespan/expected_instance['LB'])
assert fmean(oracle_scores)==oracle['fitness']==s['Oracle_fitness']
assert oracle_Cmax==[r['Oracle_Cmax'] for r in oracle['instances']]
valid_pairs={k:r for k,r in results.items() if k.endswith('_WS') and r['valid']}
best=max(valid_pairs,key=lambda k:valid_pairs[k]['fitness'])
assert valid_pairs[best]['fitness']==s['best_pair']['fitness']
h01=results['H0_H1_WS']['fitness']
assert s['H01_rank_among_valid_pairs']==1+sum(r['fitness']>h01 for r in valid_pairs.values())
assert s['counts']['above_H0_H1_WS']==sum(r['fitness']>h01 for r in valid_pairs.values())
assert s['pair_valid']==len(valid_pairs) and s['costs']['new_API_requests']==0
with (out/'Fitness_matrix.csv').open('w',newline='') as handle:
    writer=csv.writer(handle,lineterminator='\n');writer.writerow(['row_H / column_H']+[f'H{i}' for i in range(10)])
    for i in range(10):
        row=[]
        for j in range(10):
            identifier=f'H{i}' if i==j else f'H{min(i,j)}_H{max(i,j)}_WS'
            row.append(results[identifier]['fitness'] if results[identifier]['valid'] else None)
        writer.writerow([f'H{i}']+row)
b.v2.csv_write(out/'Certified_instance_call_costs.csv',call_costs)
atomic_json(out/'Dataset_manifest.json',{'protocol_sha256':b.v2.sha(out/'Protocol.json'),
    'purpose':'portable read-only Baseline-A result dataset; no scheduler/API dependency',
    'cache_evidence_contract':p['cache_contract'],
    'results':{identifier:{'path':f'certified_results/{identifier}.json','sha256':record['result_sha256'],
        'valid':record['valid'],'fitness':results[identifier]['fitness'],'origin':record['origin'],
        'evidence_level':p['cache'][identifier]['level'] if identifier in p['cache'] else 'modern'}
        for identifier,record in state['strategies'].items()}})
from load_dataset import load
assert load(out)==results
assert len(load(out,valid_only=True))==10+len(valid_pairs)
with tempfile.TemporaryDirectory() as temporary:
    temporary=__import__('pathlib').Path(temporary);(temporary/'certified_results').mkdir()
    for name in ('Dataset_manifest.json','Protocol.json','Protocol.sha256','H_frozen.json'):
        (temporary/name).write_bytes((out/name).read_bytes())
    (temporary/'certified_results/H0.json').write_text('{}')
    try:load(temporary)
    except ValueError as error:assert 'result hash mismatch' in str(error)
    else:raise AssertionError('portable loader accepted corrupt result')
audit={'passed':True,'complete_strategy_records':55,'complete_single_H':10,'complete_valid_pairs':len(valid_pairs),
    'cached_complete_strategies':14,'new_strategies_with_exit0':normal,'new_confirmed_timeout_strategies':timeouts,
    'new_reserved_evaluations':reserved,'new_reserved_solve_passes':2*reserved,'full_instance_rows':len(rows),
    'Oracle_independent_recompute_match':True,'all_cached_objects_match_original_sources':True,
    'all_new_process_boundaries_checked':True,'old_protected_files_rechecked':True,
    'protocol_sha256':b.v2.sha(b.DEFAULT/'Protocol.json'),'API_requests':0,
    'new_certified_prefix_first_H_calls':sum(r['first_H_calls'] for r in call_costs if r['origin']=='new' and r['first_H_calls'] is not None),
    'new_certified_prefix_recheck_H_calls':sum(r['recheck_H_calls'] for r in call_costs if r['origin']=='new' and r['recheck_H_calls'] is not None),
    'failed_instance_H_calls_unknown':timeouts>0,'portable_dataset_load_and_corruption_gate_passed':True}
atomic_json(out/'Final_audit.json',audit);print(audit)
