"""Read saved records only: no candidate execution, scheduler, data loader or API.

Imports host arithmetic solely to check saved outputs against cached H columns.
No H/U program is executed; no new trajectory, fitness or intervention is made.
"""
import ast
import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean

from fjsp_usage.research.protocol import digest
from fjsp_usage.research.candidates import validate_code
from fjsp_usage.usage_v2 import VERSION
from fjsp_usage.usage_v2.execution import combine_scores, decode_output

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
RUN=ROOT/'runs/v22-gpt61-select-mix-301-20261014-v1'
ARCHIVE=ROOT/'docs/usage-space/real-gpt61-301'
PREVIOUS=ROOT/'reports/h10-decision-diversity-v1-20261020'
ARGS=('progress','candidate_pair_ratio','remaining_work_mean','remaining_work_std',
      'machine_ready_mean','machine_ready_std','previous_heuristic')
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def write(name,value):
    with (OUT/name).open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def csv_write(name,rows):
    with (OUT/name).open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(dict.fromkeys(k for row in rows for k in row)),lineterminator='\n')
        writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list,tuple)) else v
                         for k,v in row.items()} for row in rows)


def transition_count(sequence):
    return sum(a!=b for a,b in zip(sequence,sequence[1:]))


def analyze():
    index=read(ARCHIVE/'All_generated_candidates.json')
    prior_plan=read(PREVIOUS/'Plan.json')
    artifacts=read(PREVIOUS/'Artifacts.json')
    for name,expected in artifacts['files'].items():
        assert sha(PREVIOUS/name)==expected,name
    for rel,expected in prior_plan['pins'].items():
        assert sha(ROOT/rel)==expected,rel
    states=[json.loads(line) for line in gzip.open(PREVIOUS/'sampled_states.jsonl.gz','rt')]
    common={}
    for state in states:
        common.setdefault(state['physical_sha256'],state)
    structures={s['file']:s for s in prior_plan['structures_train21']}
    pins=[ARCHIVE/'All_generated_candidates.json',ARCHIVE/'All_instance_results.csv',
          ROOT/'reports/usage-v22-mechanism-ablation-301-20261017-v1/Ablation_and_fixed_H_summary.csv',
          PREVIOUS/'Plan.json',PREVIOUS/'Artifacts.json',PREVIOUS/'sampled_states.jsonl.gz',
          PREVIOUS/'Metrics.json',PREVIOUS/'Tie_sensitivity.json',
          RUN/'H_frozen.json',RUN/'Conditional_H_reassessment.json',
          ROOT/'code/fjsp_usage/usage_v2/execution.py']
    h=read(RUN/'Conditional_H_reassessment.json')
    fixed={f'H{i}':row['result'] for i,row in enumerate(h['rows'])}
    summaries=[];instances=[];joins=[];coverage={};failures=[];all_conditions=[]
    for arm in ('INIT','A','B'):
        path=RUN/f'r301/{arm}/checkpoint.json'
        pins.append(path)
        checkpoint=read(path)
        for entry in [e for e in index if e['arm']==arm]:
            identifier=entry['id']
            source=ARCHIVE/entry['source'];pins.append(source)
            tree=ast.parse(source.read_text())
            assert validate_code(source.read_text(),interface_version=VERSION,member_count=10).key==entry['code_key']
            attempt=next(a for a in checkpoint['attempts'] if a['id']==identifier)
            assert attempt['code_key']==entry['code_key']
            result=checkpoint['evaluations'][identifier]['result']
            assert result['valid']==(entry['category']=='valid')
            if not result['valid']:
                failures.append({'id':identifier,'fitness':result['fitness'],'completed_instances':len(result['instances']),
                    'failure':{k:result.get(k) for k in ('failed_instance','error','error_type')},
                    'trace_steps_available':sum(len(r.get('state_trajectory',[])) for r in result['instances']),
                    'notice':'Failure prefix excluded from complete-valid state-use census; missing coverage is unknown.'})
                continue
            assert [r['file'] for r in result['instances']]==[s['file'] for s in prior_plan['structures_train21']]
            assert math.isclose(result['fitness'],entry['fitness'],abs_tol=1e-12)
            assert math.isclose(result['fitness'],fmean(r['score'] for r in result['instances']),abs_tol=1e-12)
            loaded={n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
            modes=Counter();supports=Counter();members=Counter();dominant=Counter();weight_mass=Counter()
            vectors=set();weight_vectors=set();ranges=defaultdict(list);predicates={}
            changed=Counter();steps=0;within_dynamic=0;matched=[]
            margins=[]
            for row in result['instances']:
                trace=row['state_trajectory'];decisions=row['usage_decisions'];info=structures[row['file']]
                assert row['diagnostic_status']=='complete' and len(trace)==len(decisions)==info['operations']
                assert digest([{k:t[k] for k in ('mode','vector','support','weights','dominant','chosen')} for t in trace])==row['training_behavior_sha256']
                assert math.isclose(row['score'],-row['makespan']/row['lower_bound'],abs_tol=1e-12)
                for t,d in zip(trace,decisions):
                    assert [t[k] for k in ('mode','vector','support','weights','dominant')]==d
                    modes[t['mode']]+=1;supports[tuple(t['support'])]+=1;dominant[t['dominant']]+=1
                    vectors.add(tuple(t['vector']));weight_vectors.add(tuple(t['weights']))
                    for i in t['support']:members[i]+=1;weight_mass[i]+=t['weights'][i];ranges[i].append(t['weights'][i])
                    if identifier=='A/g0000/000000':margins.append(t['vector'][9]-t['vector'][4])
                local={
                    'raw_output_switches':transition_count([(t['mode'],t['vector']) for t in trace]),
                    'support_switches':transition_count([t['support'] for t in trace]),
                    'weight_switches':transition_count([t['weights'] for t in trace]),
                    'dominant_switches':transition_count([t['dominant'] for t in trace]),
                    'mode_switches':transition_count([t['mode'] for t in trace])}
                changed.update(local);steps+=len(trace)
                within_dynamic+=int(local['support_switches']>0 or local['weight_switches']>0 or local['mode_switches']>0)
                comparisons={name:row['makespan']-next(r['makespan'] for r in ref['instances'] if r['file']==row['file']) for name,ref in fixed.items()}
                instances.append({'id':identifier,'file':row['file'],'steps':len(trace),**local,
                    'supports':dict(Counter(str(t['support']) for t in trace)),
                    'dominant_counts':dict(Counter(t['dominant'] for t in trace)),
                    'makespan':row['makespan'],'score':row['score'],'Cmax_minus_H0':comparisons['H0'],
                    'Cmax_minus_fixed_members':comparisons})
                for key,predicate in row['predicate_coverage']['predicates'].items():
                    target=predicates.setdefault(key,{k:predicate[k] for k in ('line','expression','kind','proof')})
                    for k in ('evaluations','true','false'):target[k]=target.get(k,0)+predicate[k]
                # Reconstruct record identities only; no priorities or decisions are generated.
                if row['file'] in prior_plan['selected']:
                    cursors=[0]*info['jobs'];jr=[0]*info['jobs'];mr=[0]*info['machines']
                    for t in trace:
                        physical={'cursors':cursors,'job_ready':jr,'machine_ready':mr}
                        key=digest([row['file'],physical])
                        sample=common.get(key)
                        if sample is not None:
                            # Six nonhistory scalars and the physical action set must agree.
                            assert all(t['state'][k]==sample['state'][k] for k in ARGS[:-1])
                            assert t['action_count']==len(sample['actions'])
                            decoded=decode_output((t['mode'],tuple(t['vector'])),10)
                            scores,_=combine_scores(dict(enumerate(sample['raw_scores'])),decoded['weights'],decoded['support'])
                            choice=max(range(len(scores)),key=lambda a:scores[a])
                            assert sample['actions'][choice]==[t['chosen'][k] for k in ('job','operation','machine','start','end')]
                            equal=[choice==a for a in sample['top_actions']]
                            match={'id':identifier,'file':row['file'],'step':t['step'],'sample_id':sample['id'],
                                'physical_sha256':key,'previous_heuristic':t['state']['previous_heuristic'],
                                'cache_driver_previous':sample['state']['previous_heuristic'],
                                'matches_H_top':equal,'support':t['support'],'weights':t['weights'],
                                'chosen':t['chosen'],'same_as_some_H_top':any(equal),
                                'strictly_below_all_H_maxima':all(sample['raw_scores'][i][choice]<max(sample['raw_scores'][i]) for i in range(10))}
                            joins.append(match);matched.append(match)
                        j,o,m,start,end=[t['chosen'][k] for k in ('job','operation','machine','start','end')]
                        assert cursors[j]==o and start==max(jr[j],mr[m]) and end>start
                        cursors[j]+=1;jr[j]=mr[m]=end
            control={k:v for k,v in predicates.items() if v['kind'] in ('If','IfExp','While')}
            for key,predicate in control.items():
                all_conditions.append({'id':identifier,'predicate_id':key,**predicate})
            coverage[identifier]=predicates
            summary={'id':identifier,'mode':'SELECT' if set(modes)=={0} else 'MIX',
                'fitness':result['fitness'],'steps':steps,'transitions':steps-len(result['instances']),
                'loaded_state_args':[a for a in ARGS if a in loaded],
                'syntactic_args_note':'Loaded AST name is not evidence of marginal information value.',
                'active_h_counts':dict(sorted(members.items())),'support_counts':{str(k):v for k,v in supports.items()},
                'dominant_counts':dict(sorted(dominant.items())),'weight_mass':dict(sorted(weight_mass.items())),
                'active_weight_ranges':{i:[min(v),max(v)] for i,v in ranges.items()},
                'unique_raw_vectors':len(vectors),'unique_normalized_weights':len(weight_vectors),**dict(changed),
                'within_instance_dynamic_instances':within_dynamic,
                'control_conditions':len(control),'control_never_true':sum(v['evaluations']>0 and v['true']==0 for v in control.values()),
                'control_not_evaluated':sum(v['evaluations']==0 for v in control.values()),
                'control_both_outcomes':sum(v['true']>0 and v['false']>0 for v in control.values()),
                'matched_common_states':len(matched),
                'common_agreement_H':[sum(r['matches_H_top'][i] for r in matched) for i in range(10)],
                'static_H_matching_all_common':[i for i in range(10) if matched and all(r['matches_H_top'][i] for r in matched)],
                'common_not_any_H_top':sum(not r['same_as_some_H_top'] for r in matched),
                'common_strict_below_all_maxima':sum(r['strictly_below_all_H_maxima'] for r in matched)}
            if margins:summary['H9_minus_H4_selection_score_range']=[min(margins),max(margins)]
            summaries.append(summary)
        del checkpoint
    write('Candidate_behavior.json',summaries)
    write('Predicate_coverage.json',coverage)
    write('Failure_scope.json',failures)
    csv_write('Candidate_behavior.csv',[{k:v for k,v in s.items() if k!='syntactic_args_note'} for s in summaries])
    csv_write('Instance_behavior_and_scores.csv',instances)
    csv_write('Control_conditions.csv',all_conditions)
    csv_write('Common_state_joins.csv',joins)
    write('Evidence_index.json',{'analysis':'Read-only saved-data analysis V1',
        'source_pins':{str(p.relative_to(ROOT)):sha(p) for p in pins},
        'complete_valid_candidates':len(summaries),'complete_instances':len(instances),
        'original_steps':sum(s['steps'] for s in summaries),'cached_rows':len(states),
        'cached_unique_physical_states':len(common),'exact_physical_joins':len(joins),
        'U_program_executions':0,'H_program_executions':0,'new_solves':0,'new_model_requests':0,
        'dataset_files_opened':0,'network_calls':0,
        'common_state_method':'Join actual U trace by file+cursors+job_ready+machine_ready to cached H columns. Own previous_heuristic retained; different histories are not treated as identical seven-input contexts. Native host arithmetic checks original chosen action, never executes U/H.',
        'limits':'No label of favorable h, no U-information-value diagnostic, no static-weight replay; unmatched states remain unknown.'})
    print('Complete:',len(summaries),'valid U;',len(instances),'old instance results;',len(joins),'exact physical joins; no U/H execution or solves.')


if __name__=='__main__':
    analyze()
