"""Bounded paired training diagnostic; unchanged native executor, no generated U.

prepare: read/check/freeze only. run: two reference checks and twelve state pairs.
Native constructor replays authenticated saved outputs to the intervention step;
the trusted diagnostic driver then chooses H0/H1 once and H0 thereafter.
"""
import argparse
import copy
import gzip
import json
import time
from dataclasses import asdict
from pathlib import Path

from fjsp_usage.offline_v2 import _SchedulingState
from fjsp_usage.research.candidates import compile_candidate
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import checked_candidate
from fjsp_usage.research_real.runtime import _collect
from fjsp_usage.usage_v2.execution import construct_usage_schedule
from llm4ad.task.optimization.fjsp_set import load_instance
from tools.diagnose_h_decision_diversity import (
    preflight, advance, universe, sha, read, FIELDS, CORE,
)

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
RUN=ROOT/'runs/v22-gpt61-select-mix-301-20261014-v1'
PRIOR=ROOT/'reports/h10-decision-diversity-v1-20261020'


def write(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def snapshot(state):
    return {'scheduled':[asdict(op) for op in state.scheduled],
        'selected_members':state.selected_members[:], 'cursors':state.cursors[:],
        'job_ready':state.job_ready[:], 'machine_ready':state.machine_ready[:],
        'remaining_work':[list(row) for row in state.remaining_work],
        'time_scale':state.time_scale, 'candidate_bound':state.candidate_bound,
        'total_operations':state.total_operations, 'features':dict(state.features()._asdict())}


def restore(instance,prefix):
    state=_SchedulingState(instance)
    for step,row in enumerate(prefix):
        if row['step']!=step or row['state']!=dict(state.features()._asdict()):
            raise ValueError('archived pre-state mismatch')
        advance(state,tuple(row['chosen'][k] for k in FIELDS),row['dominant'])
    return state


def select_states(rows,names):
    pool=[r for r in rows if r['driver'] in ('B3','B5') and r['step']>0 and len(r['actions'])>=10]
    controls=[]
    for name in names:
        candidates=[r for r in pool if r['file']==name and r['top_actions'][0]==r['top_actions'][1]]
        if candidates:
            controls.append(min(candidates,key=lambda r:(abs(r['state']['progress']-.5),r['step'],r['driver'])))
    controls.sort(key=lambda r:(abs(r['state']['progress']-.5),names.index(r['file']),r['step'],r['driver']))
    control_by_name={r['file']:r for r in controls[:2]}
    if len(control_by_name)!=2:
        raise ValueError('two nontrivial agreement controls unavailable')
    selected=[]
    for i,name in enumerate(names):
        targets=[.5] if name in control_by_name else [.25,.75]
        for j,target in enumerate(targets):
            driver=('B3','B5')[(i+j)%2]
            candidates=[r for r in pool if r['file']==name and r['driver']==driver
                        and r['top_actions'][0]!=r['top_actions'][1]]
            if not candidates:
                raise ValueError('predefined disagreement stratum unavailable; no adaptive replacement')
            selected.append(min(candidates,key=lambda r:(abs(r['state']['progress']-target),r['step'],r['id'])))
        if name in control_by_name:
            selected.append(control_by_name[name])
    if len(selected)!=12 or len({r['physical_sha256'] for r in selected})!=12:
        raise ValueError('requires twelve distinct complete physical states')
    return selected


def prepare():
    protocol,frozen,reassessment,ds,members,sources,candidates=preflight()
    old=read(PRIOR/'Plan.json')
    for path,expected in old['pins'].items():
        if sha(ROOT/path)!=expected:raise ValueError(f'prior evidence changed: {path}')
    rows=[json.loads(line) for line in gzip.open(PRIOR/'sampled_states.jsonl.gz','rt')]
    selected=select_states(rows,old['selected'])
    checkpoint=read(RUN/'r301/B/checkpoint.json')
    index=read(ROOT/'docs/usage-space/real-gpt61-301/All_generated_candidates.json')
    for driver,number in [('B3',3),('B5',5)]:
        key=f'B/g0000/{number:06d}'
        attempt=next(x for x in checkpoint['attempts'] if x['id']==key)
        entry=next(x for x in index if x['id']==key)
        if not attempt['code_key']==entry['code_key']==candidates[driver].key:
            raise ValueError('real U prefix provenance mismatch')
    instances={}
    files={}
    for name in old['selected']:
        path=ds.paths['train'][list(ds.names['train']).index(name)]
        if sha(path)!=protocol['dataset']['hashes'][name]:raise ValueError('training instance changed')
        instances[name]=load_instance(path);files[name]=str(path.relative_to(ROOT))
    (OUT/'states').mkdir();(OUT/'results').mkdir()
    specifications=[]
    for number,sample in enumerate(selected):
        key=f'B/g0000/{3 if sample["driver"]=="B3" else 5:06d}'
        result=checkpoint['evaluations'][key]['result']
        row=next(x for x in result['instances'] if x['file']==sample['file'])
        trace=row['state_trajectory']
        if not result['valid'] or row['diagnostic_status']!='complete':raise ValueError('complete original evidence required')
        if digest([{k:r[k] for k in ('mode','vector','support','weights','dominant','chosen')} for r in trace])!=row['training_behavior_sha256']:
            raise ValueError('original behavior hash mismatch')
        prefix=[{k:r[k] for k in ('step','state','mode','vector','support','weights','dominant','chosen')}
                for r in trace[:sample['step']]]
        restored=restore(instances[sample['file']],prefix)
        actions,inputs=universe(restored)
        if (actions!=[tuple(a) for a in sample['actions']] or inputs!=[tuple(a) for a in sample['action_inputs']]
                or dict(restored.features()._asdict())!=sample['state']):
            raise ValueError('full legal actions/inputs/state cannot be restored exactly')
        physical={k:getattr(restored,k) for k in ('cursors','job_ready','machine_ready')}
        if digest([sample['file'],physical])!=sample['physical_sha256']:raise ValueError('physical state identity mismatch')
        spec={'id':f'S{number:02d}','file':sample['file'],'sample_id':sample['id'],'source_U':key,
            'source_native_result_hash':row['deterministic_schedule_sha256'],
            'step':sample['step'],'group':'agreement' if sample['top_actions'][0]==sample['top_actions'][1] else 'disagreement',
            'action_count':len(actions),'snapshot':snapshot(restored),'prefix':prefix,
            'recommendations':[actions[sample['top_actions'][i]] for i in (0,1)],
            'branch_order':[0,1] if number%2==0 else [1,0]}
        spec['snapshot_sha256']=digest(spec['snapshot'])
        write(OUT/'states'/f'{spec["id"]}.json',spec);specifications.append({k:v for k,v in spec.items() if k not in ('prefix','snapshot')})
    # Negative checks use existing records, never commit or solve an altered case.
    first=read(OUT/'states/S00.json');instance=instances[first['file']]
    bad=copy.deepcopy(first['prefix']);bad[0]['chosen']['start']+=1
    try:restore(instance,bad)
    except ValueError:pass
    else:raise AssertionError('tampered append start accepted')
    bad=copy.deepcopy(first['prefix']);bad[0]['chosen']['operation']+=1
    try:restore(instance,bad)
    except ValueError:pass
    else:raise AssertionError('tampered next-operation cursor accepted')
    altered=copy.deepcopy(first['snapshot']);altered['machine_ready'][0]+=1
    if digest(altered)==first['snapshot_sha256']:raise AssertionError('tampered state accepted')
    # Two narrow native reference checks, both on existing small Behnke3 train.
    validation_name='Behnke3.fjsp'
    source=next(r for r in checkpoint['evaluations']['B/g0000/000003']['result']['instances'] if r['file']==validation_name)
    validation={'file':validation_name,'trace':[{k:r[k] for k in ('step','state','mode','vector','support','weights','dominant','chosen')} for r in source['state_trajectory']],
        'expected_U_hash':source['deterministic_schedule_sha256'],
        'expected_H0_schedule_hash':next(r for r in reassessment['rows'][0]['result']['instances'] if r['file']==validation_name)['deterministic_schedule_sha256']}
    write(OUT/'Reference_checks_input.json',validation)
    pins=[Path(__file__),RUN/'H_frozen.json',RUN/'Conditional_H_reassessment.json',RUN/'protocol.json',
          RUN/'r301/B/checkpoint.json',PRIOR/'Plan.json',PRIOR/'sampled_states.jsonl.gz',
          ROOT/'data/fjsp_manifest.json',ROOT/'tools/diagnose_h_decision_diversity.py',
          ROOT/'code/fjsp_usage/research_real/runtime.py',*[ROOT/p for p in CORE],
          *[ROOT/p for p in files.values()],*sorted((OUT/'states').glob('*.json')),OUT/'Reference_checks_input.json']
    write(OUT/'Plan.json',{'kind':'Task4A-controlled-continuation-train-v1','new_model_requests':0,'new_U_candidates':0,
        'selection':'Reuse prior six structural instances in their fixed order. Source pool: archived B3/B5, step>0, >=10 legal actions. Two controls are the per-instance agreement states nearest progress .5, selecting the two closest instances (ties: prior instance order, step, B3 before B5). Control instances receive one disagreement near .5; other instances receive two near .25/.75. Disagreement source alternates B3/B5 by (instance_index+target_index)%2; closest progress, then lower step. No fitness/outcome selection or fallback.',
        'samples':specifications,'training_instance_files':files,
        'continuation':'After ONE native H0/H1 SELECT decision, always native H0 raw-score single-member path; original prefix outputs replayed verbatim; previous_heuristic always updated by native executor.',
        'semantics':'Use unchanged native executor from empty state to authenticate/reproduce complete prefix, then intervene. Diagnostic controller is trusted host test fixture, not a generated/registered U. Prefix replay cost is included.',
        'pair_deadline_seconds':15,'deadline_scope':'Per state: H0 branch and H1 branch, each primary+deterministic recheck, share a SINGLE native runtime._collect 15-second worker deadline (stricter than separate 15s per branch). No retry/time extension.',
        'pair_count':12,'disagreement_count':10,'agreement_controls':2,'max_paired_native_solves':48,
        'reference_checks':2,'reference_deadline_seconds':15,'max_all_native_solves':50,
        'failure':'Any branch failure makes paired delta null. Preserve completed certified branches; timeout work not certified is unknown. Integrity failure stops remaining pairs. No automatic rerun.',
        'analysis':'Delta=Cmax(H1 action; then H0)-Cmax(H0 action; then H0), positive favors H0. Controls separate. Descriptive all-six-continuous-feature Spearman vs Delta/LB, previous member categorical, progress <.5/>=.5. No predictor, p-value, feature selection or test split; repeated states within instance are not independent.',
        'offline_checks':{'complete_prefix_actions_inputs_features_restored':True,'negative_wrong_start_rejected':True,'negative_wrong_operation_rejected':True,'negative_changed_snapshot_hash_rejected':True},
        'pins':{str(p.relative_to(ROOT)):sha(p) for p in pins}})
    print('PREPARED: twelve frozen states; zero native solves, requests or holdout opens.')


class RecordedDriver:
    def __init__(self,prefix,forced):self.prefix,self.forced,self.cursor=prefix,forced,0
    def __call__(self,*features):
        step=self.cursor;self.cursor+=1
        if step<len(self.prefix):
            row=self.prefix[step]
            if row['state']!=dict(zip(('progress','candidate_pair_ratio','remaining_work_mean','remaining_work_std','machine_ready_mean','machine_ready_std','previous_heuristic'),features)):
                raise ValueError('native prefix state mismatch')
            return row['mode'],tuple(row['vector'])
        member=self.forced if step==len(self.prefix) else 0
        return 0,tuple(1.0 if i==member else 0.0 for i in range(10))


def solve(instance,rules,spec,member):
    mirror=_SchedulingState(instance);phases={'prefix':[0]*10,'forced':[0]*10,'continuation':[0]*10}
    costs=[];step=spec['step'];prefix=spec['prefix']
    def trace(row):
        index=row['step']
        if row['state']!=dict(mirror.features()._asdict()):raise ValueError('native observer state mismatch')
        if index<step:
            if any(row[k]!=prefix[index][k] for k in ('chosen','mode','dominant')) or tuple(row['vector'])!=tuple(prefix[index]['vector']):
                raise ValueError('native prefix differs from original commit/output')
        elif index==step:
            if snapshot(mirror)!=spec['snapshot'] or digest(snapshot(mirror))!=spec['snapshot_sha256']:
                raise ValueError('complete intervention state mismatch')
            if [row['chosen'][k] for k in FIELDS]!=list(spec['recommendations'][member]):
                raise ValueError('forced native h argmax differs from cached recommendation')
        if index>=step:
            expected=member if index==step else 0
            if row['mode']!=0 or row['support']!=(expected,) or row['dominant']!=expected:
                raise ValueError('forced member / frozen continuation violated')
        phase='prefix' if index<step else 'forced' if index==step else 'continuation'
        for i,n in row['h_calls'].items():phases[phase][i]+=n
        advance(mirror,tuple(row['chosen'][k] for k in FIELDS),row['dominant'])
    started=time.perf_counter()
    result=construct_usage_schedule(instance,rules,RecordedDriver(prefix,member),trace=trace,max_actions=0,cost=costs.append)
    elapsed=time.perf_counter()-started
    if [asdict(o) for o in result.schedule.operations[:step]]!=spec['snapshot']['scheduled']:
        raise ValueError('native complete prefix schedule mismatch')
    if [sum(phases[p][i] for p in phases) for i in range(10)]!=list(result.member_calls):
        raise ValueError('h call phase accounting mismatch')
    return result,{'wall_seconds':elapsed,'phase_h_calls':phases,'h_calls':list(result.member_calls),
        'selected_h_scoring_seconds':sum(c['selected_h_scoring_seconds'] for c in costs),
        'combination_processing_seconds':sum(c['combination_processing_seconds'] for c in costs)}


def reference_worker(pipe,task,members,instances,names,allowed_modes=None):
    try:
        rules=tuple(compile_candidate(c) for c in members);instance=instances[0]
        h0=construct_usage_schedule(instance,rules,RecordedDriver([],0))
        archived=construct_usage_schedule(instance,rules,RecordedDriver(task['trace'],0))
        if digest(asdict(h0.schedule))!=task['expected_H0_schedule_hash'] or digest(asdict(archived))!=task['expected_U_hash']:
            raise ValueError('native reference identity failure')
        pipe.send({'file':names[0],'passed':True,'native_solves':2,'H0_schedule_hash':digest(asdict(h0.schedule)),
            'B3_complete_native_result_hash':digest(asdict(archived)),
            'h_calls':sum(h0.member_calls)+sum(archived.member_calls)})
    except Exception as exc:pipe.send({'error':str(exc),'error_type':type(exc).__name__})
    finally:pipe.close()


def paired_worker(pipe,spec,members,instances,names,allowed_modes=None):
    completed={}
    try:
        rules=tuple(compile_candidate(c) for c in members)
        for member in spec['branch_order']:
            first,cost=solve(instances[0],rules,spec,member)
            second,recheck=solve(instances[0],rules,spec,member)
            if first!=second:raise ValueError('deterministic recheck mismatch')
            result={'state_id':spec['id'],'forced_member':member,'makespan':first.schedule.makespan,
                'lower_bound':first.lower_bound,'score':first.score,'schedule_sha256':digest(asdict(first.schedule)),
                'native_result_sha256':digest(asdict(first)),'recheck_native_result_sha256':digest(asdict(second)),
                'schedule':asdict(first.schedule),'primary':cost,'recheck':recheck,
                'forced_action':spec['recommendations'][member],'forced_history_member':first.selected_members[spec['step']],
                'prefix_snapshot_sha256':spec['snapshot_sha256'],'full_prefix_and_constant_H0_suffix_checked':True}
            write(OUT/'results'/f'{spec["id"]}_H{member}.json',result)
            completed[str(member)]={k:v for k,v in result.items() if k!='schedule'}
        delta=completed['1']['makespan']-completed['0']['makespan']
        if spec['group']=='agreement' and completed['0']['schedule_sha256']!=completed['1']['schedule_sha256']:
            raise ValueError('same-action control schedules differ under history-independent H0 continuation')
        pipe.send({'file':names[0],'state_id':spec['id'],'valid':True,'branches':completed,'delta_H1_minus_H0':delta,
            'normalized_delta':delta/completed['0']['lower_bound']})
    except Exception as exc:pipe.send({'error':str(exc),'error_type':type(exc).__name__,'completed_branches':completed})
    finally:pipe.close()


def run():
    plan=read(OUT/'Plan.json')
    for relative,expected in plan['pins'].items():
        if sha(ROOT/relative)!=expected:raise ValueError(f'frozen input changed: {relative}')
    write(OUT/'Execution_started.json',{'started':True,'no_automatic_resume_or_retry':True})
    frozen=read(RUN/'H_frozen.json')
    members=tuple(checked_candidate(m['candidate'],'h') for m in frozen['members'])
    instances={name:load_instance(ROOT/relative) for name,relative in plan['training_instance_files'].items()}
    reference=read(OUT/'Reference_checks_input.json')
    results,error=_collect(reference_worker,reference,members,(instances[reference['file']],),(reference['file'],),15)
    write(OUT/'Native_reference_checks.json',{'valid':error is None,'results':results,'failure':error})
    if error:
        print('STOP: native reference check failed; no paired outcomes collected.');return
    pairs=[]
    for item in plan['samples']:
        spec=read(OUT/'states'/f'{item["id"]}.json')
        started=time.perf_counter()
        rows,error=_collect(paired_worker,spec,members,(instances[spec['file']],),(spec['file'],),15)
        if error:
            result={'file':spec['file'],'state_id':spec['id'],'valid':False,'delta_H1_minus_H0':None,'normalized_delta':None,
                'failure':error,'certified_branch_files':[str(p.relative_to(OUT)) for p in sorted((OUT/'results').glob(f'{spec["id"]}_H*.json'))]}
        else:result=rows[0]
        result['parent_wall_seconds']=time.perf_counter()-started
        write(OUT/'results'/f'{spec["id"]}_pair.json',result);pairs.append(result)
        print(spec['id'],spec['file'],spec['group'],'delta',result['delta_H1_minus_H0'],flush=True)
        if error and error['error_type']!='Timeout':break
    unchanged=all(sha(ROOT/p)==v for p,v in plan['pins'].items())
    write(OUT/'Completion.json',{'planned_pairs':12,'attempted_pairs':len(pairs),'complete_pairs':sum(p['valid'] for p in pairs),
        'input_pins_unchanged':unchanged,'dataset_opened':list(plan['training_instance_files']),
        'holdout_opened':False,'new_model_requests':0,'new_U_candidates':0,
        'note':'Paired local training diagnostics only; no U fitness or search result. Failed deltas remain null; no retries.'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','run'))
    args=parser.parse_args()
    prepare() if args.stage=='prepare' else run()
