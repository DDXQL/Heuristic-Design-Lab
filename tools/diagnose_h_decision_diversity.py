#!/usr/bin/env python3
"""One bounded train-only observation, not a fitness evaluation or policy search.

Uses native H0/H1 endpoint drivers and authenticated B3/B5 archived commits.
All observation code is local to this tool; the production executor is unchanged.
"""
import argparse
import gzip
import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import fmean

from fjsp_usage.offline_v2 import _SchedulingState, lower_bound_v5
from fjsp_usage.research.candidates import compile_candidate, validate_code
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_receipt, check_result, check_seal, checked_candidate
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.usage_v2 import VERSION
from fjsp_usage.usage_v2.execution import (
    UsageResultV2, combine_scores, construct_usage_schedule, decode_output,
)
from llm4ad.task.optimization.fjsp_set.scheduler import Schedule, ScheduledOperation, validate_schedule

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/v22-gpt61-select-mix-301-20261014-v1'
ARCHIVE = ROOT / 'docs/usage-space/real-gpt61-301'
OUT = ROOT / 'reports/h10-decision-diversity-v1-20261020'
CORE = ('code/fjsp_usage/offline_v2.py', 'code/fjsp_usage/usage_v2/execution.py',
        'code/fjsp_usage/research/candidates.py', 'code/fjsp_usage/research/protocol.py',
        'code/fjsp_usage/research_real/staged_evaluation.py',
        'code/llm4ad/task/optimization/fjsp_set/instances.py',
        'code/llm4ad/task/optimization/fjsp_set/scheduler.py')
FIELDS = ('job', 'operation', 'machine', 'start', 'end')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def universe(state):
    """Mirror enumeration only. Never supplies a decision to the native executor."""
    actions, inputs = [], []
    for j, job in enumerate(state.instance.jobs):
        o = state.cursors[j]
        if o == len(job):
            continue
        for m, p in job[o].alternatives:
            start = max(state.job_ready[j], state.machine_ready[m])
            actions.append((j, o, m, start, start + p))
            inputs.append((float(p), float(state.remaining_work[j][o]), len(job) - o,
                           float(state.job_ready[j]), float(state.machine_ready[m]),
                           float(start), float(start + p)))
    return actions, inputs


def advance(state, chosen, dominant):
    j, o, m, start, end = chosen
    if not (0 <= j < len(state.instance.jobs) and o == state.cursors[j]
            and o < len(state.instance.jobs[j])):
        raise ValueError('unreachable job/operation')
    alternatives = dict(state.instance.jobs[j][o].alternatives)
    if m not in alternatives or start != max(state.job_ready[j], state.machine_ready[m]) or end != start + alternatives[m]:
        raise ValueError('illegal archived append action')
    state.scheduled.append(ScheduledOperation(*chosen))
    state.cursors[j] += 1
    state.job_ready[j] = state.machine_ready[m] = end
    state.selected_members.append(dominant)


def ranks(values):
    """Descending average ranks for exact numeric ties; stable order for winners."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    result = [0.] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        for k in order[i:j]:
            result[k] = (i + 1 + j) / 2
        i = j
    return result, order


def rho(a, b):
    ma, mb = fmean(a), fmean(b)
    va, vb = sum((x-ma)**2 for x in a), sum((x-mb)**2 for x in b)
    return sum((x-ma)*(y-mb) for x,y in zip(a,b)) / math.sqrt(va*vb) if va and vb else None


def structure(name, instance):
    ops = [op for job in instance.jobs for op in job]
    loads = [0.] * instance.machine_count
    for op in ops:
        for m, p in op.alternatives:
            loads[m] += p / len(op.alternatives)
    return {'file': name, 'jobs': len(instance.jobs), 'machines': instance.machine_count,
            'operations': len(ops), 'alternatives_mean': fmean(len(o.alternatives) for o in ops),
            'flexibility': fmean(len(o.alternatives) for o in ops) / instance.machine_count,
            'nominal_max_load_share': max(loads)/sum(loads)}


def select(rows):
    features = [[math.log(r[k]) for k in ('jobs','machines','operations')]
                + [r['flexibility'], r['nominal_max_load_share']] for r in rows]
    lo, hi = list(map(min,zip(*features))), list(map(max,zip(*features)))
    vectors = [[(x-a)/(b-a) if b>a else 0 for x,a,b in zip(v,lo,hi)] for v in features]
    selected = [max(range(len(rows)), key=lambda i: rows[i]['operations'])]
    while len(selected) < 6:
        candidates = [i for i in range(len(rows)) if i not in selected]
        selected.append(max(candidates, key=lambda i: min(
            sum((a-b)**2 for a,b in zip(vectors[i],vectors[j])) for j in selected)))
    return [rows[i]['file'] for i in selected]


def preflight():
    p, h, re = [read(RUN / name) for name in
                ('protocol.json','H_frozen.json','Conditional_H_reassessment.json')]
    for relative in CORE:
        if sha(ROOT / relative) != p['implementation']['files'][relative]:
            raise ValueError(f'scheduling semantics changed: {relative}')
    ds = StagedDataset(ROOT/'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    if ds.metadata != p['dataset'] or len(ds.names['train']) != 21:
        raise ValueError('original train identity mismatch')
    check_seal(h, kind='H_frozen', mode='real', context=digest(p))
    check_seal(re, kind='Conditional_H_reassessment', mode='real', context=h['context'])
    if h['source_hash'] != re['artifact_sha256'] or h['scope_approval']['source_H_sha256'] != re['source_H_hash']:
        raise ValueError('frozen provenance mismatch')
    if h['training_files'] != list(ds.names['train']) or re['training_files'] != h['training_files']:
        raise ValueError('H training data mismatch')
    if h['member_count'] != 10 or len(h['members']) != 10 or len(re['rows']) != 10:
        raise ValueError('exact original ten H required')
    members = []
    for i,(m,row) in enumerate(zip(h['members'],re['rows'])):
        c = checked_candidate(m['candidate'],'h')
        check_receipt(m['receipt'],c,'real')
        review = m['review']
        if (m['member_id'] != i or m['id'] != row['source_row']['id']
                or m['candidate'] != row['source_row']['candidate']
                or review['reviewed_code_key'] != c.key
                or review['sample_sha256'] != digest(review['samples'])):
            raise ValueError('H numbering/code/review mismatch')
        check_result(row['result'], ds.names['train'])
        members.append(c)
    if [c.key for c in members] != h['scope_approval']['member_code_keys']:
        raise ValueError('scope/order mismatch')
    sources = {'H0': ROOT/'docs/usage-space/h01-weight-search-501-prepared/sources/alpha_100.py',
               'H1': ROOT/'docs/usage-space/h01-weight-search-501-prepared/sources/alpha_000.py'}
    index = read(ARCHIVE/'All_generated_candidates.json')
    for label, number in [('B3',3),('B5',5)]:
        row = next(x for x in index if x['id'] == f'B/g0000/{number:06d}')
        sources[label] = ARCHIVE/row['source']
        if validate_code(sources[label].read_text(),interface_version=VERSION,member_count=10).key != row['code_key']:
            raise ValueError('U archive identity mismatch')
    candidates = {k:validate_code(v.read_text(),interface_version=VERSION,member_count=10) for k,v in sources.items()}
    # Explicitly check the reused endpoint drivers; no new U source is generated.
    for name, member in [('H0',0),('H1',1)]:
        expected = f'return (1, ({", ".join("1.0" if i==member else "0.0" for i in range(10))}))'
        if expected not in candidates[name].code:
            raise ValueError('fixed endpoint driver changed')
    return p,h,re,ds,members,sources,candidates


def observe(state, driver, name, step, rules, policies, chosen):
    actions, inputs = universe(state)
    columns = [[float(h(*args)) for args in inputs] for h in rules]
    if not all(math.isfinite(v) for col in columns for v in col):
        raise ValueError('nonfinite shadow score')
    rank_and_order = [ranks(col) for col in columns]
    tops = [x[1][0] for x in rank_and_order]
    choices = {}
    for label, u in policies.items():
        decoded = decode_output(u(*state.features()),10)
        scores,_ = combine_scores(dict(enumerate(columns)),decoded['weights'],decoded['support'])
        winner = max(range(len(actions)),key=lambda a:scores[a])
        choices[label] = {**decoded, 'action_index':winner}
    actual = tuple(chosen[k] for k in FIELDS)
    if tuple(actions[choices[driver]['action_index']]) != actual:
        raise ValueError('shadow driver choice differs from authenticated/native choice')
    for i in range(10):
        if tops[i] != max(range(len(actions)),key=lambda a:columns[i][a]):
            raise ValueError('stable ranking differs from native argmax')
    # Full hidden state is recorded for audit, never made available to U.
    physical = {'cursors':state.cursors[:], 'job_ready':state.job_ready[:], 'machine_ready':state.machine_ready[:]}
    return {'id':f'{name}/{driver}/{step:04d}', 'file':name, 'driver':driver, 'step':step,
            'state':dict(state.features()._asdict()), 'physical_state':physical,
            'physical_sha256':digest([name,physical]), 'actions':actions, 'action_inputs':inputs,
            'raw_scores':columns, 'ranks':[x[0] for x in rank_and_order],
            'stable_rankings':[x[1] for x in rank_and_order], 'top_actions':tops,
            'top_tie_sizes':[sum(x == hi for x in col) for col in columns for hi in [max(col)]],
            'distinct_top_actions':len(set(tops)), 'choices':choices,
            'actual_chosen':actual}


def replay_archive(instance, row, candidate, sample_steps, collect):
    trace = row['state_trajectory']
    if row['diagnostic_status'] != 'complete' or len(trace) != instance.operation_count:
        raise ValueError('incomplete archived trajectory')
    if digest([{k:r[k] for k in ('mode','vector','support','weights','dominant','chosen')} for r in trace]) != row['training_behavior_sha256']:
        raise ValueError('archived behavior hash mismatch')
    state = _SchedulingState(instance)
    u = compile_candidate(candidate)
    calls, decisions = [0]*10, []
    for step, item in enumerate(trace):
        if item['step'] != step or dict(state.features()._asdict()) != item['state']:
            raise ValueError('unreachable archived state')
        d = decode_output(u(*state.features()),10)
        for k in ('mode','vector','support','weights','dominant'):
            if json.dumps(d[k]) != json.dumps(item[k]):
                raise ValueError(f'archived U output mismatch: {k}')
        action_count = sum(len(instance.jobs[j][state.cursors[j]].alternatives)
                           for j in range(len(instance.jobs)) if state.cursors[j] < len(instance.jobs[j]))
        if action_count != item['action_count']:
            raise ValueError('incomplete legal action count')
        for i in d['support']:
            calls[i] += action_count
        decisions.append((d['mode'],d['vector'],d['support'],d['weights'],d['dominant']))
        if step in sample_steps:
            collect(state,step,item['chosen'])
        advance(state,tuple(item['chosen'][k] for k in FIELDS),d['dominant'])
    schedule = Schedule(tuple(state.scheduled),max(x.end for x in state.scheduled))
    validate_schedule(instance,schedule)
    lb = lower_bound_v5(instance)
    reconstructed = UsageResultV2(schedule,tuple(state.selected_members),lb,-schedule.makespan/lb,
                                  tuple(decisions),tuple(calls))
    if digest(asdict(reconstructed)) != row['deterministic_schedule_sha256']:
        raise ValueError('reconstructed complete native result hash mismatch')
    return {'method':'archived legal commits; no new full solve', 'makespan':schedule.makespan,
            'native_result_hash_matches':True, 'steps_verified':len(trace), 'new_native_h_calls':0}


def matrix(rows, method):
    result, counts = [], []
    # Equal-weight trajectory/instance strata; average over states within stratum.
    for i in range(10):
        rr, cc = [], []
        for j in range(10):
            groups = {}
            for r in rows:
                v = float(r['top_actions'][i] == r['top_actions'][j]) if method=='agreement' else rho(r['ranks'][i],r['ranks'][j])
                if v is not None:
                    groups.setdefault((r['file'],r['driver']),[]).append(v)
            rr.append(fmean(fmean(v) for v in groups.values()) if groups else None)
            cc.append(sum(map(len,groups.values())))
        result.append(rr);counts.append(cc)
    return {'values':result,'defined_states':counts}


def summarize(rows):
    eligible = [r for r in rows if len(r['actions']) >= 2]
    seen = set(); unique = []
    for r in eligible:
        if r['physical_sha256'] not in seen:
            seen.add(r['physical_sha256']);unique.append(r)
    result = {'samples':len(rows), 'nontrivial_samples':len(eligible), 'unique_physical_nontrivial':len(unique),
        'agreement':matrix(eligible,'agreement'), 'spearman':matrix(eligible,'spearman'),
        'unique_physical_agreement_micro':[[fmean(float(r['top_actions'][i]==r['top_actions'][j]) for r in unique) for j in range(10)] for i in range(10)],
        'at_least_10_actions_agreement':matrix([r for r in eligible if len(r['actions'])>=10],'agreement'),
        'distinct_top_distribution':dict(sorted(Counter(r['distinct_top_actions'] for r in eligible).items())),
        'top_tie_state_rates':[fmean(r['top_tie_sizes'][i]>1 for r in eligible) for i in range(10)],
        'per_driver':{}, 'per_instance':{}, 'bins':{}, 'mix':{}}
    for field,key in [('driver','per_driver'),('file','per_instance')]:
        for value in sorted({r[field] for r in rows}):
            subset=[r for r in eligible if r[field]==value]
            result[key][value]={'n':len(subset),'mean_distinct':fmean(r['distinct_top_actions'] for r in subset),
                'near_pairs':{f'H{i}/H{j}':{'agreement':fmean(r['top_actions'][i]==r['top_actions'][j] for r in subset),
                    'spearman':fmean(v for r in subset if (v:=rho(r['ranks'][i],r['ranks'][j])) is not None)}
                    for i,j in [(1,3),(4,5),(6,7),(8,9)]}}
    for label,test in [('progress_0_20',lambda r:r['state']['progress']<.2),
                       ('progress_20_40',lambda r:.2<=r['state']['progress']<.4),
                       ('progress_40_60',lambda r:.4<=r['state']['progress']<.6),
                       ('progress_60_80',lambda r:.6<=r['state']['progress']<.8),
                       ('progress_80_100',lambda r:r['state']['progress']>=.8),
                       ('actions_2_9',lambda r:2<=len(r['actions'])<10),
                       ('actions_10_49',lambda r:10<=len(r['actions'])<50),
                       ('actions_50_199',lambda r:50<=len(r['actions'])<200),
                       ('actions_200_plus',lambda r:len(r['actions'])>=200)]:
        subset=[r for r in eligible if test(r)]
        result['bins'][label]={'n':len(subset),'mean_distinct':fmean(r['distinct_top_actions'] for r in subset) if subset else None,
            'mean_pairwise_disagreement':fmean(sum(r['top_actions'][i]!=r['top_actions'][j] for i in range(10) for j in range(i))/45 for r in subset) if subset else None}
    for label in ('B3','B5'):
        def agrees(r,i):return r['choices'][label]['action_index']==r['top_actions'][i]
        result['mix'][label]={'n':len(eligible), 'agreement_with_H':[fmean(agrees(r,i) for r in eligible) for i in range(10)],
            'matches_no_H_top':sum(r['choices'][label]['action_index'] not in r['top_actions'] for r in eligible),
            'matches_neither_active_H':sum(not any(agrees(r,i) for i in r['choices'][label]['support']) for r in eligible),
            'by_driver':{d:{'n':len(sub:=[r for r in eligible if r['driver']==d]),
                'different_from_dominant':sum(not agrees(r,r['choices'][label]['dominant']) for r in sub),
                'matches_no_H_top':sum(r['choices'][label]['action_index'] not in r['top_actions'] for r in sub)}
                for d in ('H0','H1','B3','B5')}}
    result['B3_B5_choice_agreement']=fmean(r['choices']['B3']['action_index']==r['choices']['B5']['action_index'] for r in eligible)
    return result


def checks():
    assert ranks([4,4,1]) == ([1.5,1.5,3.0],[0,1,2])
    assert rho([1,2,3],[3,2,1]) == -1.
    assert rho([2,2],[1,2]) is None
    assert rho([1],[1]) is None
    p,h,re,ds,members,sources,candidates = preflight()
    # One real training-state enumeration; no scheduling/evaluation in --check.
    from llm4ad.task.optimization.fjsp_set import load_instance
    state=_SchedulingState(load_instance(ds.paths['train'][0]))
    actions,inputs=universe(state)
    assert len(actions)==sum(len(job[0].alternatives) for job in state.instance.jobs)
    try:
        advance(state,(0,1,0,0,1),0)
    except ValueError:
        pass
    else:
        raise AssertionError('illegal operation accepted')
    assert state.scheduled==[]
    print('PASS: ranks/ties/undefined correlations; frozen H/U identity; legal-action count; rejected illegal commit; zero solves/network requests')


def run():
    started=time.perf_counter()
    p,h,re,ds,members,sources,candidates = preflight()
    instances=ds.load('train')
    structures=[structure(n,x) for n,x in zip(ds.names['train'],instances)]
    selected=select(structures)
    pins=[RUN/'protocol.json',RUN/'H_frozen.json',RUN/'Conditional_H_reassessment.json',
          RUN/'r301/B/checkpoint.json',ARCHIVE/'All_generated_candidates.json',
          ROOT/'data/fjsp_manifest.json',Path(__file__), *sources.values(),*ds.paths['train'],
          *[ROOT/r for r in CORE]]
    OUT.mkdir(exist_ok=False)
    write(OUT/'Plan.json',{'kind':'H10-reachable-common-state-observation-v1',
        'new_model_requests':0,'new_policies':0,'new_fitness_evaluations':0,
        'train_only':True,'instances_selected_without_policy_scores':True,
        'selection':'Greedy farthest-point structure coverage, squared Euclidean minmax-normalized [log J, log M, log Q, mean alternatives/M, nominal max load share]; initial largest Q; manifest-order ties. Six instances.',
        'nominal_load':'For each operation, distribute p_m/k across its k alternatives. Max machine share; descriptive proxy, not scheduled utilization.',
        'structures_train21':structures,'selected':selected,'drivers':{k:str(v.relative_to(ROOT)) for k,v in sources.items()},
        'sampling':'16 deterministic indices floor(t*(Q-1)/15), t=0..15, on each of four paths. No score-based sample selection.',
        'primary_matrix':'States with >=2 legal actions; equal instance-driver strata, then equal states per stratum. Exact top ties follow native stable enumeration; Spearman average ranks for ties; constant columns undefined.',
        'sensitivity':'Unique physical states (micro average; ignores previous_heuristic only for H ranking) and >=10 actions.',
        'no_new_full_MIX_solves':True,'max_new_fixed_endpoint_replays':12,
        'time_notice':'Observer/scoring time is diagnostic overhead, not a comparable solver benchmark. No fitness, timeout or prior validity rewritten.',
        'H_order':[{'member_id':i,'source_id':m['id'],'code_key':m['candidate']['key']} for i,m in enumerate(h['members'])],
        'original_H_seal':h['artifact_sha256'],
        'pins':{str(x.relative_to(ROOT)):sha(x) for x in pins}})
    rules=tuple(compile_candidate(c) for c in members)
    policies={k:compile_candidate(c) for k,c in candidates.items()}
    checkpoint=read(RUN/'r301/B/checkpoint.json')
    results={k:checkpoint['evaluations'][f'B/g0000/{v:06d}']['result'] for k,v in [('B3',3),('B5',5)]}
    for label,v in [('B3',3),('B5',5)]:
        check_result(results[label],ds.names['train'])
        attempt=next(a for a in checkpoint['attempts'] if a['id']==f'B/g0000/{v:06d}')
        if attempt['code_key'] != candidates[label].key:
            raise ValueError('checkpoint candidate identity mismatch')
    samples,paths=[],[]
    with gzip.open(OUT/'sampled_states.jsonl.gz','xt',encoding='utf-8') as stream:
        for name in selected:
            instance=instances[list(ds.names['train']).index(name)]
            steps={t*(instance.operation_count-1)//15 for t in range(16)}
            for driver in ('H0','H1','B3','B5'):
                before=time.perf_counter()
                def collect(state,step,chosen):
                    row=observe(state,driver,name,step,rules,policies,chosen)
                    stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
                    samples.append(row)
                if driver in ('B3','B5'):
                    row=next(r for r in results[driver]['instances'] if r['file']==name)
                    evidence=replay_archive(instance,row,candidates[driver],steps,collect)
                else:
                    mirror=_SchedulingState(instance)
                    def callback(item):
                        if item['state'] != dict(mirror.features()._asdict()):
                            raise ValueError('native/mirror state mismatch')
                        if item['step'] in steps:
                            collect(mirror,item['step'],item['chosen'])
                        advance(mirror,tuple(item['chosen'][k] for k in FIELDS),item['dominant'])
                    native=construct_usage_schedule(instance,rules,policies[driver],trace=callback,max_actions=0)
                    fixed=re['rows'][int(driver[1])]['result']['instances'][list(ds.names['train']).index(name)]
                    if digest(asdict(native.schedule)) != fixed['deterministic_schedule_sha256']:
                        raise ValueError('native H endpoint changed historical schedule')
                    evidence={'method':'one native singleton-MIX endpoint replay with observer',
                        'makespan':native.schedule.makespan,'native_result_hash_matches':True,
                        'steps_verified':instance.operation_count,'new_native_h_calls':sum(native.member_calls)}
                paths.append({'file':name,'driver':driver,**evidence,'diagnostic_wall_seconds':time.perf_counter()-before})
                print(name,driver,'verified',flush=True)
    metrics=summarize(samples)
    write(OUT/'Metrics.json',metrics)
    write(OUT/'Path_checks.json',paths)
    write(OUT/'Historical_fitness_reused.json',{'note':'Read-only prior complete train results; not produced by this diagnostic',
        **{f'H{i}':row['result']['fitness'] for i,row in enumerate(re['rows'])},
        **{k:v['fitness'] for k,v in results.items()}})
    plan=read(OUT/'Plan.json')
    for relative,expected in plan['pins'].items():
        if sha(ROOT/relative) != expected:
            raise ValueError(f'input modified during diagnostic: {relative}')
    write(OUT/'Completion.json',{'complete':True,'samples':len(samples),'paths':len(paths),
        'all_original_schedule_hashes_match':True,'input_pins_unchanged':True,
        'new_native_H_scoring_calls':sum(p['new_native_h_calls'] for p in paths),
        'sample_shadow_H_scoring_calls':sum(10*len(s['actions']) for s in samples),
        'elapsed_seconds':time.perf_counter()-started,'dataset_opened':ds.opened,
        'new_fitness_evaluations':0,'new_model_requests':0,'new_MIX_full_solves':0})
    print(json.dumps(read(OUT/'Completion.json'),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='pure offline preflight; no solve')
    args=parser.parse_args()
    checks() if args.check else run()
