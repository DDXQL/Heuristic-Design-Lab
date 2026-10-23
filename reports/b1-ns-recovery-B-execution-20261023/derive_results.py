"""Read persisted recovery/search evidence only. No U execution, API or solving."""
import csv
import ast
from collections import Counter
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import random

from fjsp_usage.research.candidates import CandidateError, parse_response
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'runs/b1-ns-recovery-B-v1-20261022'
OUT=Path(__file__).resolve().parent
INTERFACE='U-usage-v2-select-or-mix-20261012'


def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,value):
    path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def table(name,rows):
    if not rows:return
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
def total(value):return sum(value) if isinstance(value,list) else value
def cost(result):
    rows=result.get('instances',[])
    return {'certified_instances':len(rows),
        'first_seconds':sum(r.get('single_solve_seconds',0) for r in rows),
        'recheck_seconds':sum(r.get('deterministic_recheck_seconds',0) for r in rows),
        'first_h_calls':sum(total(r['single_h_calls']) for r in rows) if all('single_h_calls' in r for r in rows) else None,
        'recheck_h_calls':sum(total(r['deterministic_recheck_h_calls']) for r in rows) if all('deterministic_recheck_h_calls' in r for r in rows) else None,
        'primary_wall_seconds':result.get('primary_evaluation_seconds'),
        'failed_instance_cost_unknown':not result.get('valid',False)}


def behavior(result):
    modes=Counter();supports=Counter();dominants=Counter();vectors=set();weights=set();changes=0
    usage_changes=0;support_changes=0;mode_changes=0;same_pair_weight_changes=0;H01_weights=[]
    ranges={}
    for row in result.get('instances',[]):
        previous=None;previous_usage=None
        for mode,vector,support,normalized,dominant in row.get('usage_decisions',[]):
            modes[mode]+=1;supports[tuple(support)]+=1;dominants[dominant]+=1
            vectors.add((mode,tuple(vector)))
            w=tuple((i,normalized[i]) for i in support);weights.add(w)
            label=','.join(map(str,support));bounds=ranges.setdefault(label,{})
            for i in support:
                v=bounds.setdefault(str(i),{'min':normalized[i],'max':normalized[i]})
                v['min']=min(v['min'],normalized[i]);v['max']=max(v['max'],normalized[i])
            if previous is not None and previous != (mode,tuple(vector)):changes+=1
            previous=(mode,tuple(vector))
            usage=(tuple(support),w)
            if previous_usage is not None:
                old_mode,old_support,old_weights=previous_usage
                support_changes+=old_support!=tuple(support)
                mode_changes+=old_mode!=mode
                usage_changes+=(old_support,old_weights)!=usage
                same_pair_weight_changes+=(old_mode==mode==1 and old_support==tuple(support) and old_weights!=w)
            previous_usage=(mode,tuple(support),w)
            if mode==1 and tuple(support)==(0,1):H01_weights.append(normalized[0])
    return {'scope':'complete_train' if result.get('valid') else 'successful_prefix_only',
        'SELECT_steps':modes[0],'MIX_steps':modes[1],
        'dual_member_steps':sum(n for support,n in supports.items() if len(support)==2),
        'support_counts':{','.join(map(str,k)):v for k,v in sorted(supports.items())},
        'active_members':sorted({i for support in supports for i in support}),
        'dominant_counts':dict(sorted(dominants.items())),
        'dominant_switches':sum(r.get('member_usage',{}).get('dominant_switches',0) for r in result.get('instances',[])),
        'distinct_raw_outputs':len(vectors),'distinct_normalized_support_weights':len(weights),
        'within_instance_output_changes':changes,
        'raw_output_dynamic_observed':changes>0,'effective_usage_dynamic_observed':usage_changes>0,
        'within_instance_support_or_weight_changes':usage_changes,'support_changes':support_changes,
        'mode_changes':mode_changes,'same_pair_MIX_weight_changes':same_pair_weight_changes,
        'H01_H0_weight_min':min(H01_weights) if H01_weights else None,
        'H01_H0_weight_max':max(H01_weights) if H01_weights else None,
        'observed_normalized_weight_ranges_by_support':ranges,
        'not_same_state_counterfactual':True}


def source_forms(candidate):
    tree=ast.parse(candidate.code);returns=[];conclusive=True
    for node in ast.walk(tree):
        if not isinstance(node,ast.Return):continue
        if not isinstance(node.value,ast.Tuple) or len(node.value.elts)!=2 or not isinstance(node.value.elts[1],ast.Tuple):
            conclusive=False;continue
        mode,vector=node.value.elts
        nonzero=[i for i,v in enumerate(vector.elts) if not (isinstance(v,ast.Constant) and v.value==0)]
        literal_mode=mode.value if isinstance(mode,ast.Constant) else None
        returns.append({'mode_expression':ast.unparse(mode),'literal_mode':literal_mode,
            'nonzero_or_computed_coordinates':nonzero,
            'literal_vector':all(isinstance(v,ast.Constant) for v in vector.elts)})
    return {'returns':returns,'literal_modes_conclusive':conclusive and all(r['literal_mode'] in (0,1) for r in returns),
        'definition':'Coordinates with literal zero excluded; this is source expression coverage, not actual activation.',
        'loaded_state_names':sorted({n.id for n in ast.walk(tree) if isinstance(n,ast.Name)} & {
            'progress','candidate_pair_ratio','remaining_work_mean','remaining_work_std','machine_ready_mean','machine_ready_std','previous_heuristic'})}


def evolutionary_audit(c,j,p,parsed,accepted,pops,H):
    from fjsp_usage.research.candidates import Candidate
    from fjsp_usage.research.evolution import select_parents
    from fjsp_usage.research.sets import ranked
    from fjsp_usage.research_real.initialization import initialization_prompt
    from tools import b1_usage_prompts as prompts
    members=tuple(Candidate(m['review']['description'],m['candidate']['code'],m['candidate']['key'],'h') for m in H['members'])
    def member(ident):
        return {'id':ident,'candidate':asdict(parsed[ident]),'fitness':accepted[ident]['fitness'],
                'scores':[r['score'] for r in accepted[ident]['instances']]}
    archive=[];checked_prompts=[]
    for ident,r in j['requests'].items():
        if '/init/' not in ident:continue
        expected=initialization_prompt(prompts.build_prompt('B','I1',[],members),archive,int(ident.rsplit('/',1)[1]),
            instruction=prompts.NOVELTY,interface_version=INTERFACE)
        assert expected==r['prompt'], 'INIT prompt replay differs: '+ident
        checked_prompts.append(ident)
        if ident in accepted:archive.append(member(ident))
    assert [r['id'] for r in ranked(archive)]==[r['id'] for r in pops['P0']]
    rng=random.Random(501);rows=[];survival=[]
    for gen,values in sorted(c.get('generation_parent_pools',{}).items(),key=lambda x:int(x[0])):
        gen=int(gen);outcomes=[a for a in c['attempts'] if a['operator']!='I1' and a.get('generation')==gen]
        for a in outcomes:
            count=2 if a['operator']=='CROSS' else 1
            selected=select_parents(values,count,rng)
            assert [r['id'] for r in selected]==a['parents'] and len(set(a['parents']))==count
            assert prompts.build_prompt('B',a['operator'],selected,members)==j['requests'][a['id']]['prompt']
            checked_prompts.append(a['id']);rows.append({'id':a['id'],'parents':a['parents'],'rank_sampling_replayed':True})
        if len(outcomes)==10:
            children=[member(a['id']) for a in outcomes if a['id'] in accepted]
            expected=ranked(values+children)[:5];actual=pops['P'+str(gen+1)]
            assert [(r['id'],r['fitness'],r['candidate']['key']) for r in expected]==[(r['id'],r['fitness'],r['candidate']['key']) for r in actual]
            survival.append({'generation':gen,'offspring_surviving':[r['id'] for r in actual if r['id'] in {x['id'] for x in children}],
                'strict_champion_improvement':actual[0]['fitness']>max(r['fitness'] for r in values)})
    assert json.loads(json.dumps(rng.getstate()))==c['rng']
    return {'all_saved_prompt_bytes_replayed':len(checked_prompts),'rank_sampling_seed501_matches':True,
        'CROSS_parents':2,'MUTATE_parents':1,'one_child_per_logical_task':True,
        'parent_trace':rows,'survival':survival,'second_generation_requests':sum(a.get('generation')==1 and a['operator']!='I1' for a in c['attempts'])}


def main():
    p=read(RUN/'Protocol.json');c=read(RUN/'r501/B/checkpoint.json');j=read(RUN/'r501/B/batch_requests.json')
    oldc=read(RUN/'inherited/r501/B/checkpoint.json');oldj=read(RUN/'inherited/r501/B/batch_requests.json')
    assert len(oldj['requests'])==len(oldj['api_attempts'])==6
    for key,row in oldj['api_attempts'].items():assert j['api_attempts'][key]==row
    for key,row in oldj['requests'].items():assert j['requests'][key]==row
    assert len(j['requests'])<=40 and len(j['api_attempts'])<=60
    assert all(len(r['attempt_ids'])<=3 for r in j['requests'].values())
    H=read(RUN/'inherited/H_source_binding.json')
    cached_bounds={row['file']:row['lower_bound'] for row in H['members'][0]['training_result']['instances']}
    names=p['train_names'];outcomes={a['id']:a for a in c['attempts']}
    accepted={};behaviors={};candidate_rows=[];instance_rows=[];reported_results={};parsed_candidates={};forms={}
    for ident,record in j['requests'].items():
        a=outcomes.get(ident,{'status':'inflight_or_unprocessed','operator':'I1' if '/init/' in ident else None})
        parsed=None;parse_error=None
        if record['status']=='completed':
            raw=OUT/'responses'/(ident.replace('/','_')+'.txt');raw.parent.mkdir(exist_ok=True);raw.write_text(record['text'])
            try:parsed=parse_response(record['text'],kind='U',interface_version=INTERFACE,member_count=10)
            except CandidateError as exc:parse_error=str(exc)
        if parsed:
            parsed_candidates[ident]=parsed;forms[ident]=source_forms(parsed)
            source=OUT/'U_sources'/(ident.replace('/','_')+'.py');source.parent.mkdir(exist_ok=True);source.write_text(parsed.code)
        cache=c['evaluations'].get(ident,{})
        engine_result=cache.get('result',{});result=engine_result
        receipt=RUN/'evaluation_receipts'/((parsed.key if parsed else 'none')+'.json')
        result_source='checkpoint'
        if engine_result.get('error_type')=='BudgetStop' and receipt.exists():
            result=read(receipt);result_source='native_receipt_before_identity_rejection'
        if result:reported_results[ident]=result
        valid=engine_result.get('valid') is True
        if valid:check_result(result,names);accepted[ident]=result
        if result.get('instances'):behaviors[ident]=behavior(result)
        b=behaviors.get(ident,{})
        candidate_rows.append({'id':ident,'origin':'inherited' if ident in oldj['requests'] else 'new_after_recovery',
            'operator':a.get('operator'),'generation':a.get('generation'),'parents':json.dumps(a.get('parents',[])),
            'request_status':record['status'],'outcome':a['status'],'static_parse_pass':parsed is not None,
            'AST_key':parsed.key if parsed else None,'parse_error':parse_error,
            'duplicate_of':a.get('duplicate_of'),'evaluation_status':cache.get('status'),
            'full_valid':valid,'fitness':result.get('fitness'),'sum_Cmax_not_objective':sum(r['makespan'] for r in result['instances']) if valid else None,
            'failed_instance':result.get('failed_instance'),'error_type':result.get('error_type'),
            'engine_error_type':engine_result.get('error_type'),'result_source':result_source,
            'child_end_identity_certified':bool(engine_result.get('worker_identity')),
            'SELECT_steps':b.get('SELECT_steps'),'MIX_steps':b.get('MIX_steps'),
            'dual_member_steps':b.get('dual_member_steps'),'active_members':json.dumps(b.get('active_members')),
            'dynamic_output_observed':b.get('raw_output_dynamic_observed'),
            'dynamic_effective_usage_observed':b.get('effective_usage_dynamic_observed'),**cost(result)})
        for row in result.get('instances',[]):
            instance_rows.append({'id':ident,'full_batch_valid':valid,'file':row['file'],'Cmax':row['makespan'],
                'LB':row['lower_bound'],'LB_source':'native result','score':row['score'],'feasible':row['feasible'],
                'row_status':'complete_valid' if valid else 'successful_prefix_without_child_end_attestation',
                'error_type':None,'parent_observed_instance_seconds':None,
                'physical_hash':row.get('physical_schedule_sha256'),'recheck_hash':row.get('recheck_physical_schedule_sha256'),
                'first_seconds':row.get('single_solve_seconds'),'recheck_seconds':row.get('deterministic_recheck_seconds'),
                'first_h_scoring_seconds':row.get('selected_h_scoring_seconds'),
                'recheck_h_scoring_seconds':row.get('recheck_selected_h_scoring_seconds'),
                'first_combination_seconds':row.get('combination_processing_seconds'),
                'recheck_combination_seconds':row.get('recheck_combination_processing_seconds'),
                'first_h_calls':total(row.get('single_h_calls',0)),'recheck_h_calls':total(row.get('deterministic_recheck_h_calls',0))})
        if result.get('failed_instance'):
            failure={k:None for k in instance_rows[0]}
            failure.update(id=ident,full_batch_valid=False,file=result['failed_instance'],
                LB=cached_bounds[result['failed_instance']],LB_source='same frozen instance: cached H0 bound',
                row_status='failed_null_no_partial_fitness',error_type=result.get('error_type'),
                parent_observed_instance_seconds=result.get('parent_observed_instance_seconds'))
            instance_rows.append(failure)
    save('Behavior_profiles.json',behaviors);save('Source_forms.json',forms)
    table('Candidates.csv',candidate_rows);table('Instances.csv',instance_rows)
    save('Candidates.json',candidate_rows)
    attempts=[]
    for aid,a in j['api_attempts'].items():
        m=a.get('reply',{}).get('metadata',a.get('metadata',{})) or {};usage=a.get('usage')
        attempts.append({'attempt_id':aid,'logical_id':a['logical_id'],'number':a['number'],
            'origin':'inherited' if aid in oldj['api_attempts'] else 'new_after_recovery',
            'status':a['status'],'send_confirmed':a.get('send_confirmed'),'response_id':a.get('response_id'),
            'started_at':a.get('started_at'),'finished_at':a.get('finished_at'),'elapsed_seconds':a.get('elapsed_seconds'),
            'input_tokens':usage['input_tokens'] if usage else None,'output_tokens':usage['output_tokens'] if usage else None,
            'HTTP_status':m.get('http_status'),'model':m.get('model'),'finish_reason':m.get('finish_reason'),
            'error_type':a.get('error_type'),'error':a.get('error'),'failure_stage':m.get('failure_stage'),
            'actual_cost':None})
    table('API_attempts.csv',attempts)
    pops=dict(c.get('population_snapshots',{}));pop_rows=[]
    derived_pops=[]
    # A safety stop occurs BEFORE next generation's _prepare stores its snapshot.
    # Preserve native state; expose the already-saved generation-boundary population.
    label='P'+str(c['generation'])
    if c['generation']>0 and c['cursor']==0 and c['inflight'] is None and label not in pops:
        pops[label]=c['population'];derived_pops.append(label)
    for label,rows in pops.items():
        for row in rows:pop_rows.append({'population':label,'id':row['id'],'fitness':row['fitness'],'key':row['candidate']['key'],
            'source':'generation-boundary checkpoint; derived report only' if label in derived_pops else 'native population_snapshots'})
    table('Population_members.csv',pop_rows);save('Lineage.json',c['attempts']);save('Population_snapshots.json',pops)
    table('Lineage.csv',[{'id':a['id'],'operator':a['operator'],'generation':a.get('generation'),
        'parents':json.dumps(a.get('parents',[])),'outcome':a['status'],'fitness':accepted.get(a['id'],{}).get('fitness'),
        'in_P0':any(x['id']==a['id'] for x in pops.get('P0',[])),
        'in_P1':any(x['id']==a['id'] for x in pops.get('P1',[])),
        'in_P2':any(x['id']==a['id'] for x in pops.get('P2',[]))} for a in c['attempts']])
    # Existing reference evaluations, NEVER re-evaluated here.
    table('Fixed_H_summary.csv',[{'member':i,'key':m['candidate']['key'],'fitness':m['training_result']['fitness'],
        'sum_Cmax_not_objective':sum(row['makespan'] for row in m['training_result']['instances'])} for i,m in enumerate(H['members'])])
    save('Evolutionary_audit.json',evolutionary_audit(c,j,p,parsed_candidates,accepted,pops,H))
    references={'H0_fixed_cached':H['members'][0]['training_result']}
    b2=ROOT/'runs/h01-state-weight-search-seed501-batch-v3-20261020';plan=read(b2/'Plan.json')
    assert plan['dataset']==p['dataset'] and plan['H_order']==p['H_order'] and plan['names']==names
    core=('code/fjsp_usage/research_real/runtime.py','code/fjsp_usage/usage_v2/execution.py',
          'code/fjsp_usage/offline_v2.py','code/fjsp_usage/research_real/state_diagnostics.py')
    assert all(plan['pins'][n]==p['original_pins'][n] for n in core)
    references['H01_equal_cached']=read(b2/'results/alpha_050.json')
    references['B2_dynamic_cached']=read(b2/'r501/B/checkpoint.json')['evaluations']['B/g0001/000000']['result']
    save('Baseline_identity.json',{'dataset_names_H_and_core_identity_match':True,
        'core_files':{n:p['original_pins'][n] for n in core},
        'source_files_sha256':{str(f.relative_to(ROOT)):sha(f) for f in (RUN/'inherited/H_source_binding.json',b2/'Plan.json',
            b2/'results/alpha_050.json',b2/'r501/B/checkpoint.json')}})
    baselines=[];comparison=[]
    best=max(accepted,key=lambda k:accepted[k]['fitness']) if accepted else None
    if best:
        best=next((row['id'] for row in c['population'] if row['id'] in accepted
            and row['fitness']==accepted[best]['fitness']),best)
    for label,result in references.items():
        check_result(result,names)
        row={'baseline':label,'fitness':result['fitness'],'sum_Cmax_not_objective':sum(r['makespan'] for r in result['instances']),
            'source':'inherited H binding' if label=='H0_fixed_cached' else str(b2.relative_to(ROOT)),**cost(result)}
        if best:
            deltas=[]
            for a,b in zip(result['instances'],accepted[best]['instances']):
                assert a['lower_bound']==b['lower_bound']
                delta=(a['makespan']-b['makespan'])/a['lower_bound'];deltas.append(delta)
                comparison.append({'best_id':best,'baseline':label,'file':a['file'],'baseline_Cmax':a['makespan'],
                    'best_Cmax':b['makespan'],'LB':a['lower_bound'],'delta_F_best_minus_baseline':delta,
                    'delta_Cmax_best_minus_baseline':b['makespan']-a['makespan']})
            row.update(best_id=best,delta_F=accepted[best]['fitness']-result['fitness'],
                wins=sum(x>0 for x in deltas),losses=sum(x<0 for x in deltas),ties=sum(x==0 for x in deltas))
        baselines.append(row)
    save('Baselines.json',baselines);table('Best_vs_baselines.csv',comparison)
    current_costs=[cost(v) for v in reported_results.values()]
    complete_costs=[cost(v) for v in accepted.values()]
    new_api=[a for aid,a in j['api_attempts'].items() if aid not in oldj['api_attempts']]
    group={}
    for ident,result in accepted.items():
        group.setdefault(digest([r['physical_schedule_sha256'] for r in result['instances']]),[]).append(ident)
    save('Observed_physical_groups.json',group)
    summary={'protocol_sha256':sha(RUN/'Protocol.json'),'phase':c['phase'],'generation':c['generation'],
        'P0_formed':len(pops.get('P0',[]))==5,'initial_logicals':sum('/init/' in k for k in j['requests']),
        'derived_population_snapshots':derived_pops,
        'evolution_logicals':sum('/init/' not in k for k in j['requests']),
        'inherited_logicals':6,'inherited_API_attempts':6,'logical_tasks':len(j['requests']),
        'API_attempts':len(j['api_attempts']),'new_logicals':len(j['requests'])-6,'new_API_attempts':len(new_api),
        'retries':sum(a['number']>1 for a in j['api_attempts'].values()),
        'pending_attempts':sum(a['status'] in ('pending','interrupted_unknown') for a in j['api_attempts'].values()),
        'attempt_statuses':dict(Counter(a['status'] for a in j['api_attempts'].values())),
        'outcomes':dict(Counter(a['status'] for a in c['attempts'])),
        'stage_outcomes':{op:dict(Counter(a['status'] for a in c['attempts'] if a['operator']==op)) for op in ('I1','CROSS','MUTATE')},
        'static_legal_outputs':sum(r['static_parse_pass'] for r in candidate_rows),
        'complete_valid_candidates':len(accepted),'distinct_observed_physical_groups':len(group),
        'actual_evaluation_tasks_this_recovery':len(c['evaluations']),
        'revalidation_tasks':3,'new_candidate_evaluation_tasks':len(c['evaluations'])-3,
        'certified_successful_instance_pairs':sum(x['certified_instances'] for x in current_costs),
        'pair_count_scope':'Native recorded successful first/recheck pairs, including failed candidate prefix; not all have final child attestation.',
        'complete_valid_and_end_attested_instance_pairs':sum(x['certified_instances'] for x in complete_costs),
        'failed_candidate_prefix_pairs_without_end_attestation':sum(x['certified_instances'] for x in current_costs)-sum(x['certified_instances'] for x in complete_costs),
        'first_seconds':sum(x['first_seconds'] for x in current_costs),
        'recheck_seconds':sum(x['recheck_seconds'] for x in current_costs),
        'primary_evaluation_wall_seconds':sum(x['primary_wall_seconds'] or 0 for x in current_costs),
        'first_h_calls':sum(x['first_h_calls'] for x in current_costs),
        'recheck_h_calls':sum(x['recheck_h_calls'] for x in current_costs),
        'new_input_tokens':sum(a['usage']['input_tokens'] for a in new_api if a.get('usage')),
        'new_output_tokens':sum(a['usage']['output_tokens'] for a in new_api if a.get('usage')),
        'all_input_tokens':sum(a['usage']['input_tokens'] for a in j['api_attempts'].values() if a.get('usage')),
        'all_output_tokens':sum(a['usage']['output_tokens'] for a in j['api_attempts'].values() if a.get('usage')),
        'unknown_usage_attempts':sum(not a.get('usage') for a in j['api_attempts'].values()),
        'best_id':best,'best_fitness':accepted[best]['fitness'] if best else None,
        'population_metrics':{label:{'members':len(rows),'best':max(r['fitness'] for r in rows),
            'mean':sum(r['fitness'] for r in rows)/len(rows)} for label,rows in pops.items() if rows},
        'active_members':sorted({h for b in behaviors.values() for h in b['active_members']}),
        'observed_dual_pairs':sorted({support for b in behaviors.values() for support in b['support_counts'] if ',' in support}),
        'H01_dual_steps':sum(b['support_counts'].get('0,1',0) for b in behaviors.values()),
        'complete_valid_source_coordinate_coverage':sorted({i for ident,form in forms.items() if ident in accepted
            for row in form['returns'] for i in row['nonzero_or_computed_coordinates']}),
        'complete_valid_active_members':sorted({i for ident,b in behaviors.items() if ident in accepted for i in b['active_members']}),
        'complete_valid_mode_types':dict(Counter('SELECT_and_MIX' if b['SELECT_steps'] and b['MIX_steps'] else
            'SELECT_only' if b['SELECT_steps'] else 'MIX_only' for ident,b in behaviors.items() if ident in accepted)),
        'complete_valid_dominant_members':sorted({int(i) for ident,b in behaviors.items() if ident in accepted for i in b['dominant_counts']}),
        'complete_valid_h01_dual_steps':sum(b['support_counts'].get('0,1',0) for ident,b in behaviors.items() if ident in accepted),
        'actual_cost':None,'account_price_invoice_queries':0,'halt_reason':j['halt_reason'],
        'identity_stop':read(RUN/'Identity_stop.json') if (RUN/'Identity_stop.json').exists() else None,
        'failure_costs_not_zero_filled':True,'no_new_evaluation_or_API_in_report':True}
    save('Summary.json',summary)
    # Backup runtime evidence; immutable snapshot/source evidence remains linked, not duplicated.
    files={}
    for f in sorted(RUN.rglob('*')):
        name=f.relative_to(RUN)
        if not f.is_file() or name.parts[0] in ('source_snapshot','inherited'):continue
        raw=f.read_bytes();target=OUT/'evidence'/name;target.parent.mkdir(parents=True,exist_ok=True)
        compressed=len(raw)>20000
        if compressed:target=target.with_name(target.name+'.gz');target.write_bytes(gzip.compress(raw,mtime=0))
        else:target.write_bytes(raw)
        files[str(name)]={'sha256':hashlib.sha256(raw).hexdigest(),'archived_as':str(target.relative_to(OUT)),
            'gzip':compressed,'source_bytes':len(raw)}
    save('Evidence_manifest.json',{'source_run':str(RUN),'protocol_sha256':sha(RUN/'Protocol.json'),'files':files,
        'original_evidence':'reports/b1-ns-b-full-h-free-seed501-k2-v1-20261022/Evidence_manifest.json',
        'frozen_source_snapshot_files':p['snapshot_files']})
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
