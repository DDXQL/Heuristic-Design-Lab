"""Two primary solves; optional independent observation never changes fitness.

The original per-instance acceptance deadline covers the original two solves.
Diagnostics have a separate deadline and status, while all cost is reported.
"""
from dataclasses import asdict
import math
import multiprocessing as mp
from statistics import fmean
import time

from fjsp_usage.offline_v2 import lower_bound_v5
from llm4ad.task.optimization.fjsp_set import construct_schedule
from fjsp_usage.research.candidates import compile_candidate
from fjsp_usage.research.scheduler import construct_usage_schedule
from .diagnostics import member_usage
from .state_diagnostics import Coverage, static_diagnostics
from fjsp_usage.research.protocol import digest


def _worker(pipe, candidate, members, instances, names, allowed_modes=None):
    try:
        function = compile_candidate(candidate)
        rules = tuple(compile_candidate(m) for m in members)
        for name, instance in zip(names, instances):
            costs=[]
            extended=getattr(candidate,'interface_version',None) is not None
            if extended:
                from fjsp_usage.usage_v2.execution import construct_usage_schedule as construct_extended,usage_summary
                solve=lambda: construct_extended(instance,rules,function,
                    allowed_modes=allowed_modes if allowed_modes is not None else (0,1),cost=costs.append)
            else:
                solve = (lambda: construct_usage_schedule(instance, rules, function)) if candidate.kind == 'U' else (
                lambda: construct_schedule(instance, function))
            started = time.perf_counter()
            first = solve()
            single_seconds = time.perf_counter() - started
            first_cost=list(costs);costs.clear()
            started = time.perf_counter()
            second = solve()
            recheck_seconds = time.perf_counter() - started
            if first != second:
                raise ValueError('nondeterministic result')
            schedule = first.schedule if candidate.kind == 'U' else first
            bound = lower_bound_v5(instance)
            row = {'file': name, 'makespan': schedule.makespan, 'lower_bound': bound,
                'score': -schedule.makespan/bound, 'feasible': True,
                'single_solve_seconds': single_seconds, 'deterministic_recheck_seconds': recheck_seconds,
                'deterministic_schedule_sha256': digest(asdict(first))}
            if candidate.kind == 'U':
                row['member_usage'] = usage_summary(first,len(members)) if extended else member_usage(first.selected_members, len(members))
                if extended:
                    row.update(interface_version=candidate.interface_version,
                        usage_decisions=first.decisions,
                        single_h_calls=list(first.member_calls),
                        deterministic_recheck_h_calls=list(second.member_calls),
                        combination_processing_seconds=sum(c['combination_processing_seconds'] for c in first_cost),
                        selected_h_scoring_seconds=sum(c['selected_h_scoring_seconds'] for c in first_cost),
                        recheck_combination_processing_seconds=sum(c['combination_processing_seconds'] for c in costs),
                        recheck_selected_h_scoring_seconds=sum(c['selected_h_scoring_seconds'] for c in costs))
            pipe.send(row)
    except BaseException as exc:
        pipe.send({'error_type': type(exc).__name__, 'error': str(exc)[:500]})
    finally:
        pipe.close()


def _diagnostic_worker(pipe, candidate, members, instances, names, allowed_modes=None):
    try:
        rules = tuple(compile_candidate(m) for m in members)
        for name, instance in zip(names, instances):
            started = time.perf_counter()
            coverage = Coverage(candidate, len(members))
            observed = compile_candidate(candidate, observer=coverage.observe)
            trajectory = []
            extended=getattr(candidate,'interface_version',None) is not None
            diagnostic_costs=[]
            if extended:
                from fjsp_usage.usage_v2.execution import construct_usage_schedule as construct_extended
                traced=construct_extended(instance,rules,observed,trace=trajectory.append,max_actions=0,
                    allowed_modes=allowed_modes if allowed_modes is not None else (0,1),cost=diagnostic_costs.append)
            else:
                traced = construct_usage_schedule(instance, rules, observed,
                    trace=trajectory.append, max_actions=0)
            pipe.send({'file':name, 'diagnostic_replay_seconds':time.perf_counter()-started,
                'deterministic_schedule_sha256':digest(asdict(traced)),
                'state_trajectory':trajectory,'predicate_coverage':coverage.report(),
                **({'diagnostic_h_calls':list(traced.member_calls),
                    'diagnostic_combination_processing_seconds':sum(c['combination_processing_seconds'] for c in diagnostic_costs)} if extended else {}),
                'training_behavior_sha256':digest([
                    ({k:r[k] for k in ('mode','vector','support','weights','dominant','chosen')} if extended else
                     {'member_id':r['member_id'],'chosen':r['chosen']}) for r in trajectory])})
    except BaseException as exc:
        pipe.send({'error_type':type(exc).__name__,'error':str(exc)[:500]})
    finally:
        pipe.close()


def _collect(target, candidate, members, instances, names, timeout, allowed_modes=None):
    context=mp.get_context('spawn')
    receive,send=context.Pipe(duplex=False)
    worker=context.Process(target=target,args=(send,candidate,tuple(members),tuple(instances),tuple(names),allowed_modes))
    worker.start();send.close()
    rows,failure=[],None
    try:
        for name in names:
            started=time.monotonic()
            if not receive.poll(timeout):
                row={'error_type':'Timeout','error':'whole-instance deadline exceeded'}
            else:
                try: row=receive.recv()
                except EOFError: row={'error_type':'WorkerExit','error':'no final result'}
            if 'error' in row:
                failure={**row,'failed_instance':name,'parent_observed_instance_seconds':time.monotonic()-started}
                break
            if row['file']!=name: raise ValueError('worker instance order mismatch')
            rows.append(row)
    finally:
        receive.close();worker.join(timeout=.05)
        if worker.is_alive(): worker.terminate();worker.join(timeout=.5)
        if worker.is_alive(): worker.kill();worker.join(timeout=.5)
    return rows,failure


def evaluate(candidate, members, instances, names, *, timeout=2, diagnostics=False, diagnostic_timeout=None, allowed_modes=None):
    if not instances or len(instances)!=len(names) or not math.isfinite(timeout) or timeout<=0:
        raise ValueError('nonempty aligned split and finite positive deadline required')
    observation_timeout=timeout if diagnostic_timeout is None else diagnostic_timeout
    if not math.isfinite(observation_timeout) or observation_timeout<=0:
        raise ValueError('finite positive independent diagnostic deadline required')
    started=time.monotonic()
    rows,failure=_collect(_worker,candidate,members,instances,names,timeout,allowed_modes)
    primary_seconds=time.monotonic()-started
    if failure:
        failure['failed_instance_result']={'file':failure['failed_instance'],'makespan':None,
            'feasible':None,'valid':False,'score':None,'single_solve_seconds':None,
            'deterministic_recheck_seconds':None,'diagnostic_replay_seconds':None,
            'parent_observed_instance_seconds':failure['parent_observed_instance_seconds'],
            'note':'No certified complete solve/recheck pair; feasibility and missing solve times are unknown, not zero.'}
    result={'valid':failure is None,'total_instances':len(names),'instances':rows,
        'fitness':fmean(r['score'] for r in rows) if failure is None else None,
        'primary_evaluation_seconds':primary_seconds,**(failure or {})}
    if diagnostics and candidate.kind=='U':
        result['selector_diagnostics']=static_diagnostics(candidate.code,len(members),
            interface_version=getattr(candidate,'interface_version',None))
        result['diagnostic_scope']='independent observational replay; not fitness, validity, feedback or program equivalence'
        observed=[]; diagnostic_failure=None; diagnostic_started=time.monotonic()
        if rows:
            observed,diagnostic_failure=_collect(_diagnostic_worker,candidate,members,
                instances[:len(rows)],names[:len(rows)],observation_timeout,allowed_modes)
        for primary,trace in zip(rows,observed):
            if primary['deterministic_schedule_sha256']!=trace['deterministic_schedule_sha256']:
                # A host observation bug is not a negative strategy outcome.
                raise ValueError('diagnostic replay differs from uninstrumented schedule')
            primary.update(trace,diagnostic_status='complete')
        for primary in rows[len(observed):]:
            primary.update(diagnostic_status='not_completed',diagnostic_error=diagnostic_failure)
        result.update(diagnostic_complete=len(observed)==len(rows) and failure is None,
            diagnostic_failure=diagnostic_failure,diagnostic_evaluation_seconds=time.monotonic()-diagnostic_started,
            diagnostic_instance_timeout=observation_timeout)
    result['elapsed_seconds']=time.monotonic()-started
    return result
