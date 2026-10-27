"""B1-1C evidence analysis ONLY: saved responses/results, no U/h execution.

No provider, data loader, compiler, evaluator, shadow actions or selection call.
"""
import ast
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from statistics import fmean

from fjsp_usage.research.candidates import parse_response
from fjsp_usage.research.protocol import digest
from fjsp_usage.usage_v2 import VERSION

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
RUN=ROOT/'runs'/OUT.name
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def write(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def table(name,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    if not keys:return
    with (OUT/name).open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=keys,lineterminator='\n');w.writeheader();w.writerows(rows)


def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if sha(source)!=sha(target):raise ValueError('changed evidence copy: '+str(target))
    else:shutil.copy2(source,target)


def profile(result):
    """Count actual decoded decisions; transitions never cross instance boundaries."""
    active=Counter();dominant=Counter();supports=Counter();modes=Counter();ranges={};instances_dynamic=0
    changes=Counter();raw_unique=set();effective_unique=set();h01=[]
    rows=result.get('instances',[])
    for row in rows:
        decisions=row.get('usage_decisions',[])
        effective=[]
        for step,d in enumerate(decisions):
            mode,vector,support,weights,dom=d
            modes[mode]+=1;active.update(support);dominant[dom]+=1;supports[tuple(support)]+=1
            raw_unique.add((mode,tuple(vector)))
            effective.append((tuple(support),tuple(weights)))
            effective_unique.add(effective[-1])
            for i in support:ranges.setdefault(i,[]).append(weights[i])
            if tuple(support)==(0,1):h01.append({'file':row['file'],'step':step,'H0_weight':weights[0],'H1_weight':weights[1]})
        if len(set(effective))>1:instances_dynamic+=1
        for a,b in zip(decisions,decisions[1:]):
            changes['mode']+=a[0]!=b[0]
            changes['support']+=a[2]!=b[2]
            changes['weights']+=a[3]!=b[3]
            changes['dominant']+=a[4]!=b[4]
    return {'complete_train_valid':result.get('valid',False),'observed_instances':len(rows),
        'steps':sum(modes.values()),'mode_steps':dict(modes),'active_h_counts':dict(active),
        'dominant_h_counts':dict(dominant),'support_counts':{str(k):v for k,v in supports.items()},
        'active_weight_ranges':{str(i):[min(v),max(v)] for i,v in ranges.items()},
        'unique_raw_outputs':len(raw_unique),'unique_effective_outputs':len(effective_unique),
        'within_instance_dynamic_instances':instances_dynamic,'within_instance_switches':dict(changes),
        'H0_H1_steps':len(h01),'H0_H1_first_examples':h01[:5],
        'scope':'complete train trajectories' if result.get('valid') else 'successful prefix only; no complete fitness',
        'action_effect_of_weight_change':'unknown: no controlled same-state alternate action evidence collected'}


def source_slots(code):
    """Conservative output-slot references, NOT proof of active support/reachability."""
    mix=set();select=set();unknown=set();reads=Counter()
    tree=ast.parse(code)
    args={'progress','candidate_pair_ratio','remaining_work_mean','remaining_work_std',
          'machine_ready_mean','machine_ready_std','previous_heuristic'}
    for n in ast.walk(tree):
        if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id in args:reads[n.id]+=1
        if not isinstance(n,ast.Return):continue
        mode,vector=n.value.elts
        slots={i for i,v in enumerate(vector.elts) if not (isinstance(v,ast.Constant) and type(v.value) in (int,float) and v.value==0)}
        target=select if isinstance(mode,ast.Constant) and mode.value==0 else mix if isinstance(mode,ast.Constant) and mode.value==1 else unknown
        target.update(slots)
    return {'SELECT_nonliteral_zero_output_slots':sorted(select),'MIX_nonliteral_zero_output_slots':sorted(mix),
        'unknown_mode_nonliteral_zero_output_slots':sorted(unknown),'syntactic_state_reads':dict(reads),
        'notice':'Every return has ten slots. Nonliteral-zero slots may be dead/zero/never selected; SELECT zero entries can also win. This is source syntax, not actual member use.'}


def costs(result):
    rows=result.get('instances',[])
    fields=('single_solve_seconds','deterministic_recheck_seconds','combination_processing_seconds',
            'recheck_combination_processing_seconds','selected_h_scoring_seconds','recheck_selected_h_scoring_seconds')
    out={k:sum(r[k] for r in rows if k in r) for k in fields}
    for field in ('single_h_calls','deterministic_recheck_h_calls'):
        known=[r[field] for r in rows if field in r]
        out[field]=sum(map(sum,known)) if known else None
    out.update(primary_evaluation_seconds=result.get('primary_evaluation_seconds'),
        failed_cost_unknown=not result.get('valid',False),cost_scope='certified successful rows only; failed-instance scoring costs unknown')
    return out


def comparisons(candidate_id,result,references,names):
    output=[];summaries=[]
    for ref_id,ref in references.items():
        rr={r['file']:r for r in ref['instances']};own={r['file']:r for r in result.get('instances',[])}
        complete=result.get('valid') and len(own)==len(names)
        counts=Counter();deltas=[];same_physical=0;unknown_physical=0
        for name in names:
            a=own.get(name);b=rr[name]
            good=a is not None
            if good and a['lower_bound']!=b['lower_bound']:raise ValueError('comparison LB differs')
            delta=a['score']-b['score'] if good else None
            outcome='unknown' if delta is None else 'win' if delta>0 else 'loss' if delta<0 else 'tie'
            counts[outcome]+=1
            if good:deltas.append(delta)
            hashes=(a.get('physical_schedule_sha256'),b.get('physical_schedule_sha256')) if good else (None,None)
            same=hashes[0]==hashes[1] if all(hashes) else None
            same_physical+=same is True;unknown_physical+=same is None
            output.append({'candidate_id':candidate_id,'reference':ref_id,'file':name,'LB':b['lower_bound'],
                'candidate_Cmax':a['makespan'] if good else None,'reference_Cmax':b['makespan'],
                'candidate_Cmax_over_LB':-a['score'] if good else None,'reference_Cmax_over_LB':-b['score'],
                'delta_fitness':delta,'outcome':outcome,'same_physical_schedule':same,
                'candidate_complete_train_valid':bool(complete)})
        summaries.append({'candidate_id':candidate_id,'reference':ref_id,'complete_comparison':bool(complete),
            'fitness_delta':fmean(deltas) if complete else None,'win':counts['win'],'loss':counts['loss'],
            'tie':counts['tie'],'unknown':counts['unknown'],'same_physical_schedule_instances':same_physical,
            'unknown_physical_schedule_instances':unknown_physical,
            'notice':'Saved same-instance schedules only; no same-state causal attribution or inferential generalization test'})
    return output,summaries


def main():
    protocol=read(RUN/'Protocol.json');identity=sha(RUN/'Protocol.json')
    assert identity=='d5ec72d53583c8dd5829b6a9d8f002511956c346127aad99348e1485f8e3e898'
    assert all(sha(ROOT/n)==v for n,v in protocol['pins'].items())
    folder=RUN/'r501/B';state=read(folder/'checkpoint.json');journal=read(folder/'batch_requests.json')
    assert not (RUN/'.writer.lock').exists(), 'do not finalize analysis while writer is active'
    assert journal['policy']==protocol['config']['request_budget']
    assert len(journal['requests'])<=40 and len(journal['api_attempts'])<=60
    assert all(len(r['attempt_ids'])<=3 for r in journal['requests'].values())
    assert state['phase']!='completed' or state['generation']==2
    names=protocol['train_names'];H=read(RUN/'H_source_binding.json')
    b2run=ROOT/'runs/h01-state-weight-search-seed501-batch-v3-20261020'
    b2report=ROOT/'reports'/b2run.name
    initial=read(b2run/'Initial_population.json')
    equal=next(r['training_result'] for r in initial if r['id']=='MANUAL/init/alpha_050')
    best_path=b2run/'r501/B/checkpoint.json'
    best_b2=read(best_path)['evaluations']['B/g0001/000000']['result']
    references={'fixed_H0':H['members'][0]['training_result'],'manual_H01_equal':equal,'B2_dynamic_champion':best_b2}
    for ref in references.values():
        assert ref['valid'] and [r['file'] for r in ref['instances']]==names
        assert abs(ref['fitness']-fmean(r['score'] for r in ref['instances']))<1e-12
    candidates=[];instance_rows=[];profiles={};candidates_by_id={};raw_attempts=[];comparisons_all=[];comparison_summary=[]
    (OUT/'sources').mkdir(exist_ok=True);(OUT/'responses').mkdir(exist_ok=True)
    for row in state['attempts']:
        identifier=row['id'];request=journal['requests'][identifier];token=identifier.replace('/','_')
        candidate=None;parse_error=None
        if request['status']=='completed':
            (OUT/'responses'/(token+'.txt')).write_text(request['text'])
            try:candidate=parse_response(request['text'],kind='U',interface_version=VERSION,member_count=10)
            except Exception as exc:parse_error=type(exc).__name__+': '+str(exc)
        result=state['evaluations'].get(identifier,{}).get('result')
        if candidate:
            (OUT/'sources'/(token+'.py')).write_text(candidate.code)
            candidates_by_id[identifier]=candidate
            if row.get('code_key'):assert row['code_key']==candidate.key
        p=profile(result) if result else None
        if p:profiles[identifier]=p
        source=source_slots(candidate.code) if candidate else None
        record={'id':identifier,'stage':'INIT' if row['operator']=='I1' else f'g{row.get("generation",int(identifier.split("/")[1][1:]) if "/g" in identifier else 0)}',
            'operator':row['operator'],'parents':row['parents'],'cross_parents':2,'status':row['status'],
            'code_key':candidate.key if candidate else None,'parse_error':parse_error,
            'complete_train_valid':result.get('valid',False) if result else False,
            'fitness':result.get('fitness') if result else None,
            'Cmax_sum':sum(r['makespan'] for r in result['instances']) if result and result.get('valid') else None,
            'completed_instances':len(result.get('instances',[])) if result else 0,
            'failed_instance':result.get('failed_instance') if result else None,
            'error_type':result.get('error_type') if result else request.get('error_type'),
            'API_attempts':len(request['attempt_ids']),'accepted_attempt_id':request.get('accepted_attempt_id'),
            'source_slots':source,'behavior':p,**(costs(result) if result else {})}
        candidates.append(record)
        if result:
            for r in result.get('instances',[]):
                instance_rows.append({'id':identifier,'file':r['file'],'candidate_complete_train_valid':result['valid'],
                    'Cmax':r['makespan'],'LB':r['lower_bound'],'Cmax_over_LB':-r['score'],
                    'single_solve_seconds':r.get('single_solve_seconds'),'recheck_seconds':r.get('deterministic_recheck_seconds'),
                    'single_h_calls':sum(r['single_h_calls']) if 'single_h_calls' in r else None,
                    'recheck_h_calls':sum(r['deterministic_recheck_h_calls']) if 'deterministic_recheck_h_calls' in r else None,
                    'physical_schedule_sha256':r.get('physical_schedule_sha256')})
            if not result.get('valid') and result.get('failed_instance'):
                instance_rows.append({'id':identifier,'file':result['failed_instance'],'candidate_complete_train_valid':False,
                    'Cmax':None,'LB':None,'Cmax_over_LB':None,'error_type':result.get('error_type')})
            cr,cs=comparisons(identifier,result,references,names);comparisons_all+=cr;comparison_summary+=cs
    for attempt_id,a in journal['api_attempts'].items():
        raw_attempts.append({'attempt_id':attempt_id,'logical_id':a['logical_id'],'number':a['number'],
            'status':a['status'],'send_confirmed':a.get('send_confirmed',False),'usage':a.get('usage'),
            'input_tokens':(a.get('usage') or {}).get('input_tokens'),'output_tokens':(a.get('usage') or {}).get('output_tokens'),
            'elapsed_seconds':a.get('elapsed_seconds'),'error_type':a.get('error_type'),'retry_reason':a.get('retry_reason'),
            'http_status':a.get('metadata',{}).get('http_status'),'response_id':a.get('response_id'),
            'error':a.get('error'),'actual_cost':None})
    table('Candidates.csv',[{k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in candidates])
    write('Candidates.json',candidates);table('Instances.csv',instance_rows);table('API_attempts.csv',raw_attempts)
    write('Behavior_profiles.json',profiles);table('Instance_comparisons.csv',comparisons_all);table('Comparison_summary.csv',comparison_summary)
    # Subsequent sections operate on these saved records only.
    finalise(protocol,state,journal,candidates,profiles,references,comparison_summary,candidates_by_id,raw_attempts,b2report)


def finalise(protocol,state,journal,candidates,profiles,references,comparison_summary,code,api,b2report):
    complete=[r for r in candidates if r['complete_train_valid']]
    initial=[r for r in candidates if r['operator']=='I1']
    best=max(complete,key=lambda r:r['fitness']) if complete else None
    evolution=[r for r in complete if r['operator']!='I1']
    best_child=max(evolution,key=lambda r:r['fitness']) if evolution else None
    phase_rows=[]
    for phase,operator in [('INIT','I1'),('G1_CROSS','CROSS'),('G1_MUTATE','MUTATE'),('G2_CROSS','CROSS'),('G2_MUTATE','MUTATE')]:
        generation=None if phase=='INIT' else int(phase[1])-1
        rows=[r for r in candidates if r['operator']==operator and (generation is None or r['stage']==f'g{generation}')]
        requests=[journal['requests'][r['id']] for r in rows]
        phase_rows.append({'phase':phase,'logical_slots':len(rows),'API_attempts':sum(r['API_attempts'] for r in rows),
            'complete_responses':sum(r['status']=='completed' for r in requests),
            'syntax_legal':sum(r['code_key'] is not None for r in rows),
            'valid_new':sum(r['status']=='valid' for r in rows),'duplicates':sum(r['status']=='duplicate' for r in rows),
            'outcomes':dict(Counter(r['status'] for r in rows)),
            'best_valid_fitness':max((r['fitness'] for r in rows if r['complete_train_valid']),default=None)})
    table('Phase_summary.csv',[{**r,'outcomes':json.dumps(r['outcomes'])} for r in phase_rows])
    lineage=[];populations=[]
    snapshots=state.get('population_snapshots',{})
    for label,rows in snapshots.items():
        for r in rows:
            populations.append({'population':label,'id':r['id'],'fitness':r['fitness'],
                'origin':'LLM_initialization' if '/init/' in r['id'] else 'LLM_evolution'})
    for r in candidates:
        lineage.append({k:r[k] for k in ('id','stage','operator','parents','cross_parents','status','fitness')}|
            {label+'_survives':any(v['id']==r['id'] for v in snapshots.get(label,[])) for label in ('P0','P1','P2')})
    table('Lineage.csv',[{**r,'parents':json.dumps(r['parents'])} for r in lineage]);table('Population_members.csv',populations)
    generations=[]
    for label in ('P0','P1','P2'):
        rows=snapshots.get(label,[])
        generations.append({'population':label,'recorded':label in snapshots,'size':len(rows),
            'best_fitness':max((r['fitness'] for r in rows),default=None),
            'mean_fitness':fmean(r['fitness'] for r in rows) if rows else None,
            'ids':[r['id'] for r in rows]})
    table('Generations.csv',[{**r,'ids':json.dumps(r['ids'])} for r in generations])
    active=Counter();dominant=Counter();pairs=Counter();init_active=Counter();init_modes=Counter()
    for r in complete:
        p=profiles[r['id']];active.update(p['active_h_counts']);dominant.update(p['dominant_h_counts'])
        pairs.update({k:v for k,v in p['support_counts'].items() if len(ast.literal_eval(k))==2})
        if r['operator']=='I1':init_active.update(p['active_h_counts']);init_modes.update(p['mode_steps'])
    initial_forms=Counter()
    for r in complete:
        if r['operator']!='I1':continue
        modes=set(profiles[r['id']]['mode_steps'])
        initial_forms['SELECT_only' if modes=={0} else 'MIX_only' if modes=={1} else 'SELECT_MIX_switching']+=1
    g1ids={r['id'] for r in snapshots.get('P1',[]) if '/g0000/' in r['id']}
    g2_parent_refs=[p for r in candidates if r['stage']=='g1' for p in r['parents']]
    tokens={'input':sum((a['usage'] or {}).get('input_tokens',0) for a in api),
            'output':sum((a['usage'] or {}).get('output_tokens',0) for a in api),
            'unknown_usage_attempts':sum(a['usage'] is None for a in api)}
    cost_fields=('primary_evaluation_seconds','single_solve_seconds','deterministic_recheck_seconds',
                 'combination_processing_seconds','selected_h_scoring_seconds','single_h_calls','deterministic_recheck_h_calls')
    total_cost={k:sum(r[k] for r in candidates if r.get(k) is not None) for k in cost_fields}
    total_cost.update(failed_evaluations=sum(r['code_key'] is not None and r['status']=='invalid' for r in candidates),
        failed_instance_costs_unknown=any(r.get('failed_cost_unknown') for r in candidates),CPU_process_seconds=None)
    earliest=min((a['started_at'] for a in journal['api_attempts'].values()),default=None)
    latest=max((a.get('finished_at',a['started_at']) for a in journal['api_attempts'].values()),default=None)
    audit={'protocol_sha256':sha(RUN/'Protocol.json'),'execution_commit':'838f51086962f62184f70d3dfad551089d3ff099',
        'phase':state['phase'],'completed_generations':state['generation'],'initialization_processed':state['init_cursor'],
        'generation_cursor':state['cursor'],'logical_tasks':len(journal['requests']),
        'actual_API_attempts':len(api),'confirmed_send_attempts':sum(a['send_confirmed'] for a in api),
        'complete_responses':sum(r['status']=='completed' for r in journal['requests'].values()),
        'retry_attempts':sum(max(0,len(r['attempt_ids'])-1) for r in journal['requests'].values()),
        'pending_logical_tasks':sum(r['status']=='pending' for r in journal['requests'].values()),
        'pending_API_attempts':sum(r['status']=='pending' for r in journal['api_attempts'].values()),
        'API_statuses':dict(Counter(a['status'] for a in api)),'candidate_statuses':dict(Counter(r['status'] for r in candidates)),
        'halt_reason':journal['halt_reason'],'token_usage':tokens,'actual_cost':None,
        'cost_status':'unknown; no balance, price or invoice query performed',
        'evaluation_costs':total_cost,'first_attempt_to_last_attempt_seconds':latest-earliest if earliest is not None else None,
        'evaluation_count':len(state['evaluations']),'complete_train_valid':len(complete),
        'holdouts_evaluated':False,'new_model_or_heuristic_sources':'only authorized B1 U generation; no new H',
        'first_generation_new_survivors':sorted(g1ids),'second_generation_first_generation_parent_references':sum(p in g1ids for p in g2_parent_refs),
        'initialization_active_h_counts':dict(init_active),'initialization_mode_steps':dict(init_modes),
        'initialization_candidate_forms':dict(initial_forms),'complete_valid_active_h_counts':dict(active),
        'complete_valid_dominant_h_counts':dict(dominant),'complete_valid_dual_pair_counts':dict(pairs),
        'complete_valid_H0_H1_candidates':[r['id'] for r in complete if profiles[r['id']]['H0_H1_steps']>0],
        'best_all_generated':best['id'] if best else None,'best_evolution_child':best_child['id'] if best_child else None,
        'restart_policy':'frozen once-only evaluation and bounded API retry; no manual replays or solver retries',
        'action_effect_limit':'Output changes are observable; no same-state counterfactual action or benefit labels were generated.'}
    context=read(RUN/'B1_1C_authorization_context.json')
    audit['authorization_record_to_final_status_seconds']=(RUN/'Search_status.json').stat().st_mtime-datetime.fromisoformat(context['recorded_at_utc']).timestamp()
    audit['certified_successful_solve_passes']=2*sum(r['completed_instances'] for r in candidates)
    audit['complete_candidate_fixed_single_support']={r['id']:list(profiles[r['id']]['active_h_counts'])
        for r in complete if len(profiles[r['id']]['active_h_counts'])==1}
    for cached in state['evaluations'].values():
        for row in cached.get('result',{}).get('instances',[]):
            assert row['physical_schedule_sha256']==row['recheck_physical_schedule_sha256']==digest(row['physical_schedule'])
    audit['certified_physical_schedule_rechecks_match']=True
    for identifier,record in journal['requests'].items():
        saved=RUN/'r501/B/prompts'/identifier.replace('/','_')
        assert saved.read_text()==record['prompt']
        assert record['prompt_key']==digest({'prompt':record['prompt'],'kind':'U'})
        completed=[key for key in record['attempt_ids'] if journal['api_attempts'][key]['status']=='completed']
        if record['status']=='completed':assert completed and record['accepted_attempt_id']==completed[0]
    for r in candidates:
        expected=0 if r['operator']=='I1' else 2 if r['operator']=='CROSS' else 1
        assert len(set(r['parents']))==len(r['parents'])==expected
        if r['operator']!='I1':
            generation=str(int(r['stage'][1:]))
            assert set(r['parents'])<={p['id'] for p in state['generation_parent_pools'][generation]}
    audit['saved_prompts_and_request_hashes_match']=True
    audit['accepted_first_complete_response_verified']=True
    audit['declared_parent_counts_and_frozen_generation_pool_verified']=True
    before=read(RUN/'Protected_history_before.json')
    changed=[n for n,v in before.items() if sha(ROOT/n)!=v['sha256'] or (ROOT/n).stat().st_mtime_ns!=v['mtime_ns']]
    audit['protected_history_files']=len(before);audit['protected_history_changed']=changed
    assert not changed, 'historical record changed during B1 execution'
    write('Execution_audit.json',audit);write('Lineage.json',lineage)
    write('Reference_sources.json',{
        'same_train_identity':protocol['dataset'],'H_order':protocol['H_order'],
        'fixed_H0':{'source':str((RUN/'H_source_binding.json').relative_to(ROOT)),'source_sha256':sha(RUN/'H_source_binding.json'),
                    'code_key':read(RUN/'H_source_binding.json')['members'][0]['candidate']['key']},
        'manual_equal':{'source':'runs/h01-state-weight-search-seed501-batch-v3-20261020/Initial_population.json',
                        'id':'MANUAL/init/alpha_050','code_sha256':sha(b2report/'sources/alpha_050.py')},
        'B2_dynamic':{'source':'runs/h01-state-weight-search-seed501-batch-v3-20261020/r501/B/checkpoint.json',
                      'id':'B/g0001/000000','code_sha256':sha(b2report/'sources/B_g0001_000000.py')},
        'notice':'External frozen train21 references only. Not B1 parents, no new evaluation, no V1/test28 performance used.'})
    write('Reference_results.json',references)
    reference_rows=[{'id':key,'fitness':r['fitness'],'Cmax_sum':sum(i['makespan'] for i in r['instances']),**costs(r)} for key,r in references.items()]
    table('External_references.csv',reference_rows)
    for name in ('Protocol.json','Protocol.sha256','config.pending.json','H_source_binding.json',
                 'B1_1_authorization.json','B1_1C_authorization_context.json','Search_status.json',
                 'Final_or_partial_population.json','B1_training_report.json','Execution_B1_1C.log','Protected_history_before.json'):
        if (RUN/name).exists():copy(RUN/name,OUT/'evidence'/name)
    for name in ('checkpoint.json','batch_requests.json','events.jsonl'):
        if (RUN/'r501/B'/name).exists():copy(RUN/'r501/B'/name,OUT/'evidence'/name)
    for folder in ('r501/B/prompts','wire_responses'):
        if (RUN/folder).exists():
            for p in (RUN/folder).iterdir():
                if p.is_file():copy(p,OUT/'evidence'/Path(folder).name/p.name)
    write('Original_result_hashes.json',{str(p.relative_to(ROOT)):sha(p) for p in RUN.rglob('*') if p.is_file() and p.name!='.writer.lock'})
    render_report(audit,candidates,phase_rows,generations,profiles,references,comparison_summary,best,best_child,code)
    print(json.dumps({'phase':audit['phase'],'logical_tasks':audit['logical_tasks'],'API_attempts':audit['actual_API_attempts'],
        'statuses':audit['candidate_statuses'],'best_all':audit['best_all_generated'],'best_child':audit['best_evolution_child'],
        'H0_H1':audit['complete_valid_H0_H1_candidates'],'pairs':audit['complete_valid_dual_pair_counts']},ensure_ascii=False,indent=2))


def number(v,places=6):
    return 'NA' if v is None else f'{v:.{places}f}'


def render_report(audit,candidates,phases,generations,profiles,references,comparison_summary,best,best_child,code):
    done=audit['phase']=='completed' and audit['completed_generations']==2
    init=phases[0]
    title='两代完整完成' if done else '按当前停止状态保留结果，未完成两代'
    text=f'''# B1-1C：完整10H自由发现真实LLM Pilot

2026-10-22，Asia/Manila。**{title}。** 阶段终态 `{audit['phase']}`，完成代数 {audit['completed_generations']}。协议SHA256 `{audit['protocol_sha256']}`；执行工程提交 `{audit['execution_commit']}`。未修改冻结Prompt、H、状态、执行/评分、数据或选择规则；未访问validation11或test28进行评价、生成或选优。

## 初始化与代际执行

初始化处理 {init['logical_slots']} 个逻辑任务，真实API尝试 {init['API_attempts']} 次；完整响应 {init['complete_responses']}，语法合法 {init['syntax_legal']}，完整有效新U {init['valid_new']}，重复 {init['duplicates']}。未植入任何人工U、等权或B2冠军；有效但未达到5个时，只能称部分初始化池，不能称已建立P0。

|阶段|逻辑槽|API尝试|完整响应|语法合法|完整有效新U|重复|有效率（有效/槽）|最好新U Fitness|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    for r in phases:
        rate=r['valid_new']/r['logical_slots']*100 if r['logical_slots'] else None
        text+=f"|{r['phase']}|{r['logical_slots']}|{r['API_attempts']}|{r['complete_responses']}|{r['syntax_legal']}|{r['valid_new']}|{r['duplicates']}|{number(rate,2)}%|{number(r['best_valid_fitness'],12)}|\n"
    text+='\n未执行阶段的有效率是NA，不是0%。源码相同或候选失败不触发模型修复、重新评价或补发。完整分类见Candidates.csv和API_attempts.csv。\n\n'
    text+='|种群|是否记录|规模|最佳Fitness|平均Fitness|成员|\n|---|---|---:|---:|---:|---|\n'
    for r in generations:
        text+=f"|{r['population']}|{r['recorded']}|{r['size']}|{number(r['best_fitness'],12)}|{number(r['mean_fitness'],12)}|{', '.join(r['ids']) or 'NA'}|\n"
    text+=f'''
第一代新子代进入P1：{audit['first_generation_new_survivors']}；第二代对这些子代的父代引用共 {audit['second_generation_first_generation_parent_references']} 次。完整每次交叉/变异、两个或一个父代、有效性及P0/P1/P2存活见Lineage.csv。每代5 CROSS＋5 MUTATE、二父代交叉的配置保持；尚未执行的槽位不补算为完成。

## 全部候选

|ID|操作|状态|完整train有效|Fitness|Cmax合计|失败实例|
|---|---|---|---|---:|---:|---|
'''
    for r in candidates:
        text+=f"|{r['id']}|{r['operator']}|{r['status']}|{r['complete_train_valid']}|{number(r['fitness'],12)}|{r['Cmax_sum'] if r['Cmax_sum'] is not None else 'NA'}|{r['failed_instance'] or ''}|\n"
    text+=f'''
## 成员发现与真实行为

完整有效初始化U的形式：{audit['initialization_candidate_forms']}；初始化实际启用计数：{audit['initialization_active_h_counts']}；SELECT/MIX步骤：{audit['initialization_mode_steps']}。计数为调度步骤，不是独立实验样本。

全部完整有效U实际启用H计数：{audit['complete_valid_active_h_counts']}；实际主导H计数：{audit['complete_valid_dominant_h_counts']}。双成员组合：{audit['complete_valid_dual_pair_counts']}。完整有效且实际执行过H0/H1组合的U：{audit['complete_valid_H0_H1_candidates']}。失败候选的成功前缀单列于Behavior_profiles.json，不混入上述完整有效覆盖。

源码中每个合法return必有10个向量槽，故不能把“出现10槽”当成发现全部H。Candidates.json另列SELECT/MIX的非字面零槽位和状态变量读取，属于保守语法口径；可能为零、不可达或从未胜出。实际启用和主导按执行决策记录判定，不能用源码提及代替。

|完整有效U|模式步骤|成员支持集计数|实际动态实例数|主导切换数|权重范围|
|---|---|---|---:|---:|---|
'''
    for r in candidates:
        if not r['complete_train_valid']:continue
        p=profiles[r['id']]
        text+=f"|{r['id']}|{p['mode_steps']}|{p['support_counts']}|{p['within_instance_dynamic_instances']}|{p['within_instance_switches'].get('dominant',0)}|{p['active_weight_ranges']}|\n"
    text+='''
动态判定只依据同一实例轨迹内实际支持集/归一化权重变化，切换不跨实例首尾拼接。原始SELECT评分变化但赢家不变不能算有效成员切换；单正项MIX应按单成员执行解释。

**动作与排程的证据边界**：原主评价保存了实际使用决策和物理排程；与外部参照排程哈希不同可证明最终排程不同。同一状态下“冻结某权重会选何动作”没有采集，因此不能把输出变化、排程不同或Fitness更高直接解释为权重变化的单步因果收益。没有为报告运行影子动作、H评分、U执行或第三遍回放。

## 同身份train21外部参照

|外部参照|完整Fitness|Cmax合计（非优化目标）|
|---|---:|---:|
'''
    for name,r in references.items():text+=f"|{name}|{r['fitness']:.12f}|{sum(i['makespan'] for i in r['instances'])}|\n"
    if best:
        text+=f"\n本批最佳完整有效新程序为 `{best['id']}`，Fitness={best['fitness']:.12f}，Cmax合计={best['Cmax_sum']}。"
        if best_child:text+=f" 最佳演化子代为 `{best_child['id']}`，Fitness={best_child['fitness']:.12f}。\n"
        else:text+=' 本批没有完整有效演化子代。\n'
        text+='\n|最佳本批U相对参照|Fitness差（本批−参照）|平均Cmax/LB相对改善|胜/负/平|物理排程相同/未知实例数|\n|---|---:|---:|---|---|\n'
        for name,r in references.items():
            c=next(c for c in comparison_summary if c['candidate_id']==best['id'] and c['reference']==name)
            delta=best['fitness']-r['fitness'];relative=delta/(-r['fitness'])*100
            text+=f"|{name}|{delta:.12f}|{relative:.4f}%|{c['win']}/{c['loss']}/{c['tie']}|{c['same_physical_schedule_instances']}/{c['unknown_physical_schedule_instances']}|\n"
        text+='\n正差/正百分比有利于本批U。原始Cmax合计与逐实例LB归一化后的均值不是同一个目标，不能互换。所有有效及失败前缀的逐实例对比均保留在Instance_comparisons.csv；前缀差值不能代替完整Fitness。\n'
        text+='\n最佳真实候选源码（来自首份被接受响应，非手写示例）：\n\n```python\n'+code[best['id']].code+'```\n'
    else:text+='\n本批没有完整有效U，完整性能比较均未知，不使用成功前缀冒充完整结果。\n'
    cost=audit['evaluation_costs']
    text+=f'''
## 预算、故障与成本

- 逻辑任务 {audit['logical_tasks']}/40；真实API尝试 {audit['actual_API_attempts']}/60；确认发送尝试 {audit['confirmed_send_attempts']}；额外重试尝试 {audit['retry_attempts']}。完整响应 {audit['complete_responses']}；候选状态 {audit['candidate_statuses']}。
- pending逻辑任务/API尝试 {audit['pending_logical_tasks']}/{audit['pending_API_attempts']}；批次halt_reason={audit['halt_reason']}。失败详情及HTTP分类见API_attempts.csv，失败/重复不追加逻辑槽。
- 已知wire输入Token {audit['token_usage']['input']}、输出 {audit['token_usage']['output']}；另 {audit['token_usage']['unknown_usage_attempts']} 次usage未知，已知之和不冒充完整用量。实际费用unknown/null；不读取余额、价格或账单，也不按Token估算实扣。
- 实际候选评价 {audit['evaluation_count']}；完整有效 {audit['complete_train_valid']}。主评价包装墙钟 {number(cost['primary_evaluation_seconds'],3)} 秒；其中认证首次求解 {number(cost['single_solve_seconds'],3)} 秒，复检 {number(cost['deterministic_recheck_seconds'],3)} 秒。
- 成功认证求解 {audit['certified_successful_solve_passes']} 遍；授权记录到最终状态落盘约 {audit['authorization_record_to_final_status_seconds']:.1f} 秒（含启动与来源核验，并非精确CPU/推理时间）。
- 认证首次/复检H评分调用 {cost['single_h_calls']}/{cost['deterministic_recheck_h_calls']}；失败实例成本是否未知：{cost['failed_instance_costs_unknown']}。这些是调用数，不是调度步数。CPU进程秒未采集。
- 墙钟受资源竞争和持久化/来源核验影响，不将API尝试耗时当纯推理时间；历史H0计时不是包含U接口的同期速度对照。本轮未预留独占CPU。

## 科研解释与限制

'''
    if best:
        dynamic=profiles[best['id']]['within_instance_dynamic_instances']>0
        text+=f"LLM已自主生成可在完整21train运行的利用程序；最佳程序在已观察轨迹中{'确有动态输出' if dynamic else '未观察到有效输出动态变化'}。这只证明合法生成和完整执行，不自动证明优于静态策略。\n\n"
        delta=best['fitness']-references['manual_H01_equal']['fitness']
        text+=f"相对强静态H0/H1等权，最佳U的Fitness差为{delta:.12f}，平均归一化质量相对差为{delta/(-references['manual_H01_equal']['fitness'])*100:.4f}%（正值表示改善，负值表示尚有差距）。"
        if done:
            p0=next(r for r in generations if r['population']=='P0');p2=next(r for r in generations if r['population']=='P2')
            text+=f" P0→P2最佳Fitness变化为{p2['best_fitness']-p0['best_fitness']:.12f}；应结合谱系判断新冠军还是初始化保留。\n"
        else:text+=' 两代未完成，不能宣称获得两代演化收益。\n'
    if not done:
        text+='\n未完成阶段及停止原因以实际终态和执行日志为准；初始化不足5个有效U时没有P0、P1或P2，不会用已知优胜程序填补。本批未扩额、改提示或修复后擅自重启。\n'
    text+='''
单seed、有限候选和训练集内选优不支持稳定泛化、显著优势、七状态充分性、全部静态组合上界或搜索机制普遍有效/失效。B1与B2同时改变H空间、初始化和交叉父代数，不能把差异单独归于10H或二父代。模型父代提示不显式含Fitness，评价仅经外部生存和父代抽样间接作用。

validation11已有开发暴露，test28已消费；本批均未使用。后续性能验证需要另行冻结候选、预登记独立数据及重复设计，本轮不开展。

## 复现与证据

入口保持`tools/b1_usage_local.py`；实际命令为同一运行目录的`check`、正式授权后`run --env-file <既有本机文件>`、结束后`report`。凭证未复制至运行/报告目录。`sources/`为从已接收响应静态解析导出的源码，`responses/`保存完整成功响应；`evidence/`保存授权、协议、提示、请求账本、原始响应、检查点和终态。Original_result_hashes.json绑定原运行全部文件；Reference_sources.json说明外部参照身份，Reference_results.json是原结果副本，未重评。

本报告由`analyze_saved.py`只读上述记录生成，不调用LLM、执行候选或求解实例。历史B2/V1内容和mtime按本批开始前359项快照核对一致。所有失败、重复、未执行阶段均保留。本批到此停止，不自动进入其他搜索、消融或独立验证。
'''
    (OUT/'B1_1C_REPORT_ZH.md').write_text(text)


if __name__=='__main__':main()


