"""Read existing A1-A3 / H01 grid / B2 evidence only. No evaluator imports.

No sampling, raw-instance opens, network use or historical writes. All input
bytes are hashed and checked unchanged at the end. Python 3.12 AST identities.
"""
import ast
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import fmean,median
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/a4-evidence-protocol-20261024-v1'
GRID=ROOT/'runs/h01-state-weight-search-seed501-batch-v3-20261020'
OLD_REPORT=ROOT/'reports'/GRID.name
BASE=ROOT/'runs/tier2-baseline-a-train21-seed501-20261024-v1'
SUP=ROOT/'runs/baseline-a-supplemental-T30-seed501-20261024-v1'
INPUTS={}
GUARD={'network_attempts':0,'raw_instance_opens':0,'historical_writes':0}


def sha(data):return hashlib.sha256(data).hexdigest()


def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())


def guard(event,args):
    if event.startswith('socket.'):
        GUARD['network_attempts']+=1;raise RuntimeError('audit forbids network')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        path=Path(os.fsdecode(args[0])).resolve()
        if path.suffix=='.fjsp':GUARD['raw_instance_opens']+=1;raise RuntimeError('audit does not open raw instances')
        if (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
            if not path.is_relative_to(OUT):GUARD['historical_writes']+=1;raise RuntimeError('new audit output only')


def raw(path):
    path=Path(path).resolve();b=path.read_bytes();entry={'path':str(path.relative_to(ROOT)),'sha256':sha(b),'bytes':len(b)}
    if path in INPUTS:assert INPUTS[path]==entry,'Input changed: '+str(path)
    INPUTS[path]=entry;return b


def read(path):return json.loads(raw(path))


def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def csv_save(name,rows):
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)


def canonical_key(code):
    tree=ast.parse(code);fn=tree.body[0]
    for a in fn.args.args:a.annotation=None
    fn.returns=None
    if isinstance(fn.body[0],ast.Expr) and isinstance(fn.body[0].value,ast.Constant) and isinstance(fn.body[0].value.value,str):fn.body.pop(0)
    prefix='U-usage-v2-select-or-mix-20261012\n10\n' if fn.name=='use_heuristics' else ''
    return sha((prefix+ast.dump(tree,include_attributes=False)).encode())


def check_result(result,instances):
    assert result['valid'] is True and result['total_instances']==len(instances)==21
    assert len(result['instances'])==21
    for r,e in zip(result['instances'],instances):
        assert r['file']==e['file'] and r['lower_bound']==e['LB']
        assert type(r['makespan']) is int and r['makespan']>0 and r['feasible'] is True
        assert r['score']==-r['makespan']/e['LB']
        assert all(math.isfinite(r[k]) and r[k]>=0 for k in ('single_solve_seconds','deterministic_recheck_seconds'))
        if 'physical_schedule' in r:
            assert digest(r['physical_schedule'])==r['physical_schedule_sha256']==r['recheck_physical_schedule_sha256']
            assert r['captured_solves']==2
            if 'single_h_calls' in r:
                assert r['single_h_calls']==r.get('recheck_h_calls',r.get('deterministic_recheck_h_calls'))
        else:assert len(r['deterministic_schedule_sha256'])==64
    assert result['fitness']==fmean(r['score'] for r in result['instances'])


def compare(a,b):
    assert [r['file'] for r in a['instances']]==[r['file'] for r in b['instances']]
    delta=[x['score']-y['score'] for x,y in zip(a['instances'],b['instances'])]
    ma=-a['fitness'];mb=-b['fitness']
    return {'delta_F':a['fitness']-b['fitness'],'wins':sum(x>0 for x in delta),'losses':sum(x<0 for x in delta),
        'ties':sum(x==0 for x in delta),'mean_Cmax_over_LB_A':ma,'mean_Cmax_over_LB_B':mb,
        'relative_mean_ratio_change_pct':100*(ma/mb-1),
        'sum_Cmax_A':sum(r['makespan'] for r in a['instances']),'sum_Cmax_B':sum(r['makespan'] for r in b['instances']),
        'sum_Cmax_delta':sum(x['makespan']-y['makespan'] for x,y in zip(a['instances'],b['instances']))}


def audit():
    if sys.version_info[:2]!=(3,12):raise RuntimeError('Use repository Python3.12 historical AST format')
    OUT.mkdir(exist_ok=True);sys.addaudithook(guard)
    plan=read(GRID/'Plan.json');protocol=read(GRID/'protocol.json');sup=read(SUP/'Protocol.json')
    assert sha(raw(GRID/'Plan.json'))==protocol['plan_sha256']
    assert (protocol['config']['seeds'],protocol['config']['instance_timeout'])==([501],15)
    instances=sup['instances'];names=[r['file'] for r in instances]
    assert names==plan['names']==plan['dataset']['split']['train']
    assert all(plan['dataset']['hashes'][r['file']]==r['sha256'] for r in instances)
    frozen=read(GRID/'H_frozen.json');newh=read(SUP/'H_frozen.json')
    assert frozen['members']==newh['members'] and [m['candidate']['key'] for m in frozen['members']]==plan['H_order']==sup['H_order']
    hashes=read(OLD_REPORT/'Original_result_hashes.json')
    cp=read(GRID/'r501/B/checkpoint.json');j=read(GRID/'r501/B/budgeted_evolution_requests.json')
    initial=read(GRID/'Initial_population.json');grid_complete=read(GRID/'Grid_complete.json')
    assert grid_complete=={'references':21,'new_evaluations':16,'reused':5,'no_refinement':True}
    source_checks=[]
    science=['code/fjsp_usage/offline_v2.py','code/fjsp_usage/research/candidates.py',
        'code/fjsp_usage/usage_v2/candidates.py','code/fjsp_usage/usage_v2/execution.py',
        'code/fjsp_usage/research_real/runtime.py','code/llm4ad/task/optimization/fjsp_set/instances.py',
        'code/llm4ad/task/optimization/fjsp_set/scheduler.py','tools/usage_mechanism_ablation.py','tools/h01_weight_search.py']
    execution=read(OLD_REPORT/'Execution_audit.json')
    parent_path=ROOT/'reports/usage-fixed-pair-weight-grid-20261018-v1/Plan.json'
    parent_plan=read(parent_path);assert sha(raw(parent_path))==plan['pins'][str(parent_path.relative_to(ROOT))]
    for path in science:
        now=sha(raw(ROOT/path));expected=plan['pins'].get(path,parent_plan['pins'].get(path))
        historical=subprocess.run(['git','show',execution['execution_commit']+':'+path],cwd=ROOT,capture_output=True)
        source_checks.append({'path':path,'pinned_sha256':expected,'current_sha256':now,'current_matches':expected==now,
            'pin_origin':'B2 Plan' if path in plan['pins'] else 'B2-pinned earlier grid Plan',
            'execution_commit_matches':historical.returncode==0 and sha(historical.stdout)==expected})
    # Missing original path versions are disclosed; core mismatches cannot be silently adopted.
    assert all(r['current_matches'] for r in source_checks)
    grid={};summary=[];allrows=[];cache_records=[]
    versions=plan['versions'];assert [v['alpha'] for v in versions]==[p/100 for p in range(0,101,5)]
    for v in versions:
        path=GRID/'results'/(v['id']+'.json');result=read(path)
        assert hashes[str(path.relative_to(ROOT))]==sha(raw(path))
        assert canonical_key(v['candidate']['code'])==v['candidate']['key']
        tree=ast.parse(v['candidate']['code']);output=ast.literal_eval(tree.body[0].body[-1].value)
        mode,vector=output;assert mode==1 and vector[:2]==(v['alpha'],1-v['alpha']) and all(x==0 for x in vector[2:])
        check_result(result,instances);grid[v['id']]=result
        row={'id':v['id'],'H0_weight':v['alpha'],'H1_weight':1-v['alpha'],'valid':True,'complete_instances':21,
             'fitness':result['fitness'],'sum_Cmax':sum(r['makespan'] for r in result['instances']),
             'mean_Cmax_over_LB':-result['fitness'],'reused':v['reused'],'in_manual_P0':v['id'] in [x['id'].split('/')[-1] for x in initial],
             'candidate_key':v['candidate']['key'],'result_path':str(path.relative_to(ROOT)),'result_sha256':sha(raw(path)),
             'first_seconds':sum(r['single_solve_seconds'] for r in result['instances']),
             'recheck_seconds':sum(r['deterministic_recheck_seconds'] for r in result['instances']),
             'receipt_level':'legacy_native_recheck' if v['alpha'] in (0.,1.) else 'legacy_physical_recheck'}
        if v['reused'] and 'path' in v['reuse']:
            source=ROOT/v['reuse']['path'];assert sha(raw(source))==v['reuse']['sha256']
            assert read(source)==result
        if not v['reused']:
            started=read(GRID/'results'/(v['id']+'.started.json'));assert started['code_key']==v['candidate']['key']
        summary.append(row)
        for r in result['instances']:
            allrows.append({'id':v['id'],'H0_weight':v['alpha'],'file':r['file'],'Cmax':r['makespan'],'LB':r['lower_bound'],
                            'score':r['score'],'physical_hash':r.get('physical_schedule_sha256'),'commit_or_native_hash':r.get('commit_sequence_sha256',r.get('deterministic_schedule_sha256'))})
        cache_records.append({'id':v['id'],'result_path':str(path.relative_to(ROOT)),'sha256':row['result_sha256'],
                              'alpha':v['alpha'],'candidate_key':v['candidate']['key'],'receipt_level':row['receipt_level']})
    for row in initial:
        id=row['id'].split('/')[-1];assert row['fitness']==grid[id]['fitness'] and row['training_result']==grid[id]
    champion=max(cp['population'],key=lambda x:x['fitness']);cid=champion['id'];dynamic=cp['evaluations'][cid]['result'];check_result(dynamic,instances)
    assert hashes[str((GRID/'r501/B/checkpoint.json').relative_to(ROOT))]==sha(raw(GRID/'r501/B/checkpoint.json'))
    assert canonical_key(champion['candidate']['code'])==champion['candidate']['key']
    response=j['requests'][cid]['text'];match=re.fullmatch(r'\s*\{([^{}]+)\}\s*```python\s*\n(.*?)\n```\s*',response,re.S)
    assert match and canonical_key(match[2])==champion['candidate']['key']
    vals=[v for r in dynamic['instances'] for v in r['observed_alpha']]
    assert len(vals)==sum(r['operations'] for r in instances)==3800
    all_B2_results=[e['result'] for e in cp['evaluations'].values()]
    assert len(cp['attempts'])==20 and len(all_B2_results)==19 and all(r['valid'] for r in all_B2_results)
    for value in all_B2_results:check_result(value,instances)
    assert len(j['api_attempts'])==20 and all(r['status']=='completed' for r in j['api_attempts'].values())
    duplicates=[a for a in cp['attempts'] if a['status']=='duplicate'];assert len(duplicates)==1
    initial_ids={row['id'] for row in initial};all_attempt_ids={a['id'] for a in cp['attempts']}
    assert all(parent in initial_ids|all_attempt_ids for a in cp['attempts'] for parent in a['parents'])
    new_values=[grid[v['id']] for v in versions if not v['reused']]+all_B2_results
    best=max(summary,key=lambda r:r['fitness']);static=grid[best['id']];equal=grid['alpha_050']
    comparisons=[]
    for label,a,b_label,b in [('grid_best',static,'equal_H01',equal),('B2_dynamic',dynamic,'grid_best',static),('B2_dynamic',dynamic,'equal_H01',equal)]:
        comparisons.append({'A':label,'B':b_label,**compare(a,b)})
    detailed=[]
    for v in versions:
        for r,e,d in zip(grid[v['id']]['instances'],equal['instances'],dynamic['instances']):
            detailed.append({'id':v['id'],'file':r['file'],'Cmax':r['makespan'],'equal_Cmax':e['makespan'],'B2_Cmax':d['makespan'],
                'delta_score_vs_equal':r['score']-e['score'],'delta_score_vs_B2':r['score']-d['score']})
    # Raw A1-A3 and composite quality identity; no lookups by a sampled A4 policy.
    bs=read(BASE/'checkpoint.json');ss=read(SUP/'checkpoint.json');basep=read(BASE/'Protocol.json')
    assert bs['protocol_sha256']==sha(raw(BASE/'Protocol.json'))==(BASE/'Protocol.sha256').read_text().strip()
    assert ss['protocol_sha256']==sha(raw(SUP/'Protocol.json'))==(SUP/'Protocol.sha256').read_text().strip()
    assert basep['instances']==instances and basep['H_order']==sup['H_order']
    assert sha(raw(BASE/'H_frozen.json'))==basep['H_sha256']==sha(raw(SUP/'H_frozen.json'))
    singles={};pairs={};a_sources=[]
    for id,e in bs['strategies'].items():
        path=BASE/e['result_path'];value=read(path);assert sha(raw(path))==e['result_sha256']
        if not value['valid']:
            assert value['fitness'] is None
            replacement=ss['strategies'][id];path=SUP/replacement['result_path'];value=read(path);assert sha(raw(path))==replacement['result_sha256']
        check_result(value,instances)
        if '_WS' in id:pairs[id]=value
        else:singles[id]=value
        a_sources.append({'id':id,'path':str(path.relative_to(ROOT)),'sha256':sha(raw(path)), 'fitness':value['fitness']})
    assert len(singles)==10 and len(pairs)==45
    oracle=fmean(max(singles[f'H{i}']['instances'][k]['score'] for i in range(10)) for k in range(21))
    prior=read(ROOT/'reports'/SUP.name/'Oracle.json');assert oracle==prior['fitness']
    assert equal['fitness']==pairs['H0_H1_WS']['fitness']
    assert [r['makespan'] for r in equal['instances']]==[r['makespan'] for r in pairs['H0_H1_WS']['instances']]
    current_equal=read(SUP/ss['strategies']['H0_H1_WS']['result_path'])
    current_h0=read(SUP/ss['strategies']['H0']['result_path'])
    for oldrow,newrow in zip(equal['instances'],current_equal['instances']):
        assert oldrow['physical_schedule_sha256']==newrow['physical_schedule_sha256']
        assert oldrow['commit_sequence_sha256']==newrow['commit_sequence_sha256']
    for oldrow,newrow in zip(grid['alpha_100']['instances'],current_h0['instances']):
        assert oldrow['deterministic_schedule_sha256']==newrow['commit_sequence_sha256']
    assert grid['alpha_000']['fitness']==singles['H1']['fitness'] and grid['alpha_100']['fitness']==singles['H0']['fitness']
    # Cache candidates are indexed by metadata only; never passed to a sampler.
    cache_a=[]
    for row in a_sources:
        if row['id'].startswith('H') and '_WS' not in row['id']:
            spec={'kind':'single','member':int(row['id'][1:])}
        else:
            a,b=map(int,re.findall(r'H(\d+)',row['id']));spec={'kind':'pair','i':a,'j':b,'k':10}
        cache_a.append({'spec':spec,'path':row['path'],'sha256':row['sha256'],'receipt_level':'historical_complete_quality'})
    for v in cache_records:
        percent=int(v['id'].split('_')[1])
        if percent not in (0,50,100):
            cache_a.append({'spec':{'kind':'pair','i':0,'j':1,'k':percent//5},'path':v['result_path'],
                            'sha256':v['sha256'],'receipt_level':v['receipt_level']})
    assert len(cache_a)==73
    # Full-policy timing evidence from old new pair evaluations and new T30 six.
    costs=[]
    for row in a_sources:
        value=read(ROOT/row['path'])
        if '_WS' in row['id']:
            costs.append(sum(r['single_solve_seconds']+r['deterministic_recheck_seconds'] for r in value['instances']))
    budget={'grid_references':21,'grid_new_full_evaluations':16,'grid_reused':5,'manual_P0':5,
        'manual_P0_is_subset_of_grid':True,'B2_logical_generation_requests':20,'B2_actual_API_attempts':20,
        'B2_API_retries':0,'B2_complete_valid_new_evaluations':19,'B2_duplicate_requests':1,
        'B2_duplicate':duplicates[0],'B2_failed_solve_evaluations':0,'new_full_evaluations_grid_plus_evolution':35,
        'new_program_instance_evaluations':35*21,'new_solve_passes':35*42,
        'new_grid_and_evolution_first_seconds':sum(r['single_solve_seconds'] for value in new_values for r in value['instances']),
        'new_grid_and_evolution_recheck_seconds':sum(r['deterministic_recheck_seconds'] for value in new_values for r in value['instances']),
        'extra_grid16_in_manual_P0':False,
        'reused_program_instance_evaluations':5*21,'note':'R&D references and a single search incremental budget are different; no invoices queried.'}
    save('Grid_budget_and_identity.json',{'budget':budget,'science_sources':source_checks,'train21':instances,'H_order':plan['H_order'],
        'historical_execution_commit':execution['execution_commit'],'result_hash_manifest':str((OLD_REPORT/'Original_result_hashes.json').relative_to(ROOT)),
        'modern_PID_exit0_receipts':'not reconstructed for historical grid/B2; retained legacy two-solve evidence',
        'seed_scope':'B2 search seed501; static grid deterministic, reused native H entries have historical generation seed rather than a new seed501 solve',
        'observed_dynamic_alpha':{'min':min(vals),'max':max(vals),'distinct':len(set(vals)),'recorded_steps':len(vals)}})
    save('A1_A3_verified.json',{'single_count':10,'pair_count':45,'best_single':max(singles,key=lambda x:singles[x]['fitness']),
        'best_single_fitness':max(v['fitness'] for v in singles.values()),'best_equal_pair':max(pairs,key=lambda x:pairs[x]['fitness']),
        'best_equal_pair_fitness':max(v['fitness'] for v in pairs.values()),'single_H_Oracle_fitness':oracle,'sources':a_sources,
        'quality_table_sources':'39 original complete pairs +6 supplemental T30; not full45 concurrent T30'})
    save('Verified_quality_cache_index.json',{'status':'metadata index only, NOT queried by A4 this round',
        'entries':cache_a,'H_sha256':sha(raw(SUP/'H_frozen.json')),'H_order':sup['H_order'],'instances':instances,
        'science_sources':{r['path']:r['current_sha256'] for r in source_checks},
        'no_negative_T15_cache_reuse_at_T30':True,'cross_protocol_timing_comparable':False})
    save('Grid_summary.json',{'complete':21,'best':best,'B2_fitness':dynamic['fitness'],'comparisons':comparisons,
        'pair_construct_cost_seconds':{'min':min(costs),'median':median(costs),'mean':fmean(costs),'max':max(costs)},
        'new_FJSP_solves':0,'new_API_requests':0,'A4_formal_candidates_drawn':0})
    csv_save('H01_grid_21.csv',summary);csv_save('H01_grid_instances_441.csv',allrows)
    csv_save('Grid_B2_comparisons.csv',comparisons);csv_save('Grid_B2_instance_differences_441.csv',detailed)
    csv_save('B2_champion_instances_21.csv',[{'file':r['file'],'Cmax':r['makespan'],'LB':r['lower_bound'],'score':r['score'],
        'physical_hash':r['physical_schedule_sha256'],'commit_hash':r['commit_sequence_sha256']} for r in dynamic['instances']])
    for path,entry in INPUTS.items():assert sha(path.read_bytes())==entry['sha256'],'changed historical input'
    save('Source_manifest.json',{'inputs':list(INPUTS.values()),'unchanged_at_end':True,'guard':GUARD,
        'audit_script_sha256':sha(Path(__file__).read_bytes()),'python':sys.version,
        'no_raw_instances_opened':True,'new_solves':0,'new_API':0,'A4_samples':0})
    print(json.dumps({'grid_complete':21,'best_alpha':best['H0_weight'],'best_fitness':best['fitness'],
        'B2_fitness':dynamic['fitness'],'cache_metadata_entries':len(cache_a),'new_solves':0,'A4_samples':0},ensure_ascii=False))


if __name__=='__main__':audit()
