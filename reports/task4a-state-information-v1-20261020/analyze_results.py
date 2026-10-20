"""Describe the frozen Task4A outcomes. No solving or feature/model search."""
import csv
import json
from collections import Counter,defaultdict
from pathlib import Path
from statistics import fmean
from fjsp_usage.research.protocol import digest
from tools.diagnose_h_decision_diversity import ranks,rho

OUT=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text())
plan=read(OUT/'Plan.json');completion=read(OUT/'Completion.json')
assert completion['input_pins_unchanged']


def physical(schedule):
    return {'makespan':schedule['makespan'],'operations':sorted(
        [o[k] for k in ('job','operation','machine','start','end')] for o in schedule['operations'])}


rows=[];costs=[]
for item in plan['samples']:
    spec=read(OUT/'states'/f'{item["id"]}.json')
    pair_path=OUT/'results'/f'{item["id"]}_pair.json'
    pair=read(pair_path) if pair_path.exists() else {'valid':False,'status':'not_attempted'}
    row={'id':item['id'],'file':item['file'],'source':item['source_U'],'step':item['step'],
        'group':item['group'],**spec['snapshot']['features'],'legal_actions':spec['action_count'],
        'H0_action':json.dumps(spec['recommendations'][0]),'H1_action':json.dumps(spec['recommendations'][1]),
        'valid':pair['valid'],'Cmax_H0':None,'Cmax_H1':None,'delta_H1_minus_H0':None,
        'normalized_delta':None,'winner':None,'physical_schedules_identical':None,
        'prefix_Cmax_floor':max(o['end'] for o in spec['snapshot']['scheduled']),
        'paired_wall_seconds':pair.get('parent_wall_seconds'),'certified_h_calls':None}
    if pair['valid']:
        branches=[read(OUT/'results'/f'{item["id"]}_H{i}.json') for i in (0,1)]
        row.update(Cmax_H0=branches[0]['makespan'],Cmax_H1=branches[1]['makespan'],
            delta_H1_minus_H0=pair['delta_H1_minus_H0'],normalized_delta=pair['normalized_delta'],
            winner='H0' if pair['delta_H1_minus_H0']>0 else 'H1' if pair['delta_H1_minus_H0']<0 else 'tie',
            physical_schedules_identical=physical(branches[0]['schedule'])==physical(branches[1]['schedule']),
            certified_h_calls=sum(sum(b[k]['h_calls']) for b in branches for k in ('primary','recheck')))
        for member,b in enumerate(branches):
            costs.append({'state_id':item['id'],'member':member,
                'primary_seconds':b['primary']['wall_seconds'],'recheck_seconds':b['recheck']['wall_seconds'],
                'primary_h_calls':sum(b['primary']['h_calls']),'recheck_h_calls':sum(b['recheck']['h_calls']),
                **{f'{phase}_h_calls_primary':sum(b['primary']['phase_h_calls'][phase]) for phase in ('prefix','forced','continuation')},
                'canonical_physical_sha256':digest(physical(b['schedule']))})
    rows.append(row)
for name,data in [('Paired_results.csv',rows),('Evaluation_costs.csv',costs)]:
    with (OUT/name).open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(data[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(data)
eligible=[r for r in rows if r['valid'] and r['group']=='disagreement']
controls=[r for r in rows if r['valid'] and r['group']=='agreement']
features=('progress','candidate_pair_ratio','remaining_work_mean','remaining_work_std','machine_ready_mean','machine_ready_std')
correlations={k:rho(ranks([r[k] for r in eligible])[0],ranks([r['normalized_delta'] for r in eligible])[0]) for k in features}
categorical=defaultdict(Counter);by_instance=defaultdict(list);by_source=defaultdict(Counter)
for r in eligible:
    categorical[r['previous_heuristic']][r['winner']]+=1
    by_instance[r['file']].append({'id':r['id'],'source':r['source'],'progress':r['progress'],
                                 'delta':r['delta_H1_minus_H0'],'winner':r['winner']})
    by_source[r['source']][r['winner']]+=1
analysis={'eligible_disagreement_pairs':len(eligible),'controls':len(controls),
    'disagreement_directions':dict(Counter(r['winner'] for r in eligible)),
    'control_directions':dict(Counter(r['winner'] for r in controls)),
    'delta_range':[min(r['delta_H1_minus_H0'] for r in eligible),max(r['delta_H1_minus_H0'] for r in eligible)],
    'max_abs_difference_relative_to_better_Cmax':max(abs(r['delta_H1_minus_H0'])/min(r['Cmax_H0'],r['Cmax_H1']) for r in eligible),
    'tie_Cmax_but_different_physical_schedule':sum(r['winner']=='tie' and not r['physical_schedules_identical'] for r in eligible),
    'all_controls_exact_physical_match':all(r['physical_schedules_identical'] for r in controls),
    'six_feature_spearman_vs_delta_over_LB':correlations,'previous_member_categorical':dict(categorical),
    'source_U_groups':dict(by_source),'by_instance':dict(by_instance),
    'progress_groups':{label:dict(Counter(r['winner'] for r in eligible if predicate(r))) for label,predicate in
        [('below_0.5',lambda r:r['progress']<.5),('at_least_0.5',lambda r:r['progress']>=.5)]},
    'paired_wall_seconds':sum(r['paired_wall_seconds'] or 0 for r in rows),
    'max_pair_wall_seconds':max(r['paired_wall_seconds'] or 0 for r in rows),
    'paired_certified_h_calls':sum(r['certified_h_calls'] or 0 for r in rows),
    'reference_certified_h_calls':read(OUT/'Native_reference_checks.json')['results'][0]['h_calls'],
    'prefix_h_calls_total':2*sum(c['prefix_h_calls_primary'] for c in costs),
    'native_solves':4*len(eligible+controls)+2,
    'statistical_limits':'Descriptive only, ten disagreement states from six train instances; repeated within-instance observations and source/path confounding. No predictor or p-values; correlations are not marginal feature value or evidence of insufficiency.'}
with (OUT/'Analysis.json').open('x') as stream:json.dump(analysis,stream,ensure_ascii=False,indent=2);stream.write('\n')
print(json.dumps(analysis,ensure_ascii=False,indent=2))
