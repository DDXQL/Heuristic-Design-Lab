"""Unmodified real-source legacy U replay on train only, not new candidates."""
from dataclasses import asdict
import json
import time
from fjsp_usage.research.candidates import compile_candidate
from fjsp_usage.research.scheduler import construct_usage_schedule as legacy_schedule
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_seal,check_population,checked_candidate
from fjsp_usage.research_real.conditional_research import check_origin
from fjsp_usage.research_real.runtime import _collect
from .execution import construct_usage_schedule,LegacyAdapter


def worker(pipe,candidate,members,instances,names,allowed_modes=None):
    try:
        rules=tuple(compile_candidate(m) for m in members)
        original=compile_candidate(candidate);adapted=LegacyAdapter(original,len(members),candidate.key)
        for name,instance in zip(names,instances):
            left=[];right=[];cost=[]
            started=time.perf_counter();old=legacy_schedule(instance,rules,original,trace=left.append,max_actions=0)
            old_seconds=time.perf_counter()-started
            started=time.perf_counter();new=construct_usage_schedule(instance,rules,adapted,trace=right.append,max_actions=0,cost=cost.append)
            new_seconds=time.perf_counter()-started
            states_equal=[r['state'] for r in left]==[r['state'] for r in right]
            choices_equal=[r['chosen'] for r in left]==[r['chosen'] for r in right]
            if not (old.schedule==new.schedule and old.selected_members==new.selected_members
                    and old.score==new.score and states_equal and choices_equal):
                raise ValueError('legacy adaptation changed actions/state/history/schedule/fitness')
            pipe.send({'file':name,'makespan':new.schedule.makespan,'feasible':True,'score':new.score,
                'legacy_makespan':old.schedule.makespan,'legacy_score':old.score,
                'steps_compared':len(left),'states_equal':states_equal,'actions_equal':choices_equal,
                'history_equal':old.selected_members==new.selected_members,
                'legacy_state_sha256':digest([r['state'] for r in left]),
                'adapted_state_sha256':digest([r['state'] for r in right]),
                'legacy_action_sha256':digest([r['chosen'] for r in left]),
                'adapted_action_sha256':digest([r['chosen'] for r in right]),
                'legacy_single_solve_seconds':old_seconds,'adapted_single_solve_seconds':new_seconds,
                'adapted_combination_processing_seconds':sum(c['combination_processing_seconds'] for c in cost),
                'adapted_h_calls':new.member_calls,
                'notice':'Cross-path comparison timings, not deterministic recheck/independent diagnostic timings.'})
    except BaseException as exc:pipe.send({'error_type':type(exc).__name__,'error':str(exc)[:500]})
    finally:pipe.close()


def audit(flow):
    flow.assert_current()
    source,members,docs=check_origin(flow.project_root,flow.config,flow.dataset)
    run=flow.config.conditional_research['source_run'];old_protocol=docs[run+'/protocol.json']
    initial=docs[run+'/r101/Shared_initial.json']
    rows=check_population(initial,mode='real',context=digest(old_protocol),kind='Shared_initial',
        H_hash=source['artifact_sha256'],names=flow.dataset.names['train'],size=5)
    instances=flow.dataset.load('train');results=[]
    for row in rows:
        print('Legacy compatibility: '+row['id'],flush=True)
        candidate=checked_candidate(row['candidate'],'U')
        records,failure=_collect(worker,candidate,members,instances,flow.dataset.names['train'],flow.config.instance_timeout)
        reproduces=failure is None and [r['makespan'] for r in records]==[r['makespan'] for r in row['training_result']['instances']]
        results.append({'source_id':row['id'],'source_code_key':candidate.key,
            'original_candidate':asdict(candidate),'original_receipt':row['receipt'],
            'adapter':LegacyAdapter(None,len(members),candidate.key).binding,
            'complete_train':failure is None,'source_makespans_reproduced':reproduces,
            'instances':records,'failure':failure,'new_real_generation':False})
        flow.write('Legacy_compatibility_audit.json','Legacy_compatibility_audit',rows=results,
            complete=len(results)==len(rows),source_population_hash=initial['artifact_sha256'],
            new_real_requests=0,holdouts_evaluated=False,
            notice='Existing U kept unchanged; adapters are host replay tools, never initial/evolved candidates or new model receipts.')
    return flow.write('Legacy_compatibility_audit.json','Legacy_compatibility_audit',rows=results,
        complete=True,full_train_passed=sum(r['complete_train'] and r['source_makespans_reproduced'] for r in results),
        source_population_hash=initial['artifact_sha256'],new_real_requests=0,holdouts_evaluated=False,
        notice='Existing U kept unchanged; adapters are host replay tools, never initial/evolved candidates or new model receipts.')
