"""Existing scheduling semantics, with single solve/recheck time kept separate."""

import multiprocessing as mp
from statistics import fmean
import time

from fjsp_usage.offline_v2 import lower_bound_v5
from llm4ad.task.optimization.fjsp_set import construct_schedule
from fjsp_usage.research.candidates import compile_candidate
from fjsp_usage.research.scheduler import construct_usage_schedule


def _worker(pipe, candidate, members, instances, names):
    try:
        function = compile_candidate(candidate)
        rules = tuple(compile_candidate(m) for m in members)
        for name, instance in zip(names, instances):
            solve = (lambda: construct_usage_schedule(instance, rules, function)) if candidate.kind == 'U' else (
                lambda: construct_schedule(instance, function))
            started = time.perf_counter()
            first = solve()
            single_seconds = time.perf_counter() - started
            started = time.perf_counter()
            second = solve()
            recheck_seconds = time.perf_counter() - started
            if first != second:
                raise ValueError('nondeterministic result')
            schedule = first.schedule if candidate.kind == 'U' else first
            bound = lower_bound_v5(instance)
            pipe.send({'file': name, 'makespan': schedule.makespan, 'lower_bound': bound,
                'score': -schedule.makespan/bound, 'feasible': True,
                'single_solve_seconds': single_seconds, 'deterministic_recheck_seconds': recheck_seconds})
    except BaseException as exc:
        pipe.send({'error_type': type(exc).__name__, 'error': str(exc)[:500]})
    finally:
        pipe.close()


def evaluate(candidate, members, instances, names, *, timeout=2):
    if not instances or len(instances) != len(names) or timeout <= 0:
        raise ValueError('nonempty aligned split and finite positive deadline required')
    started = time.monotonic()
    context = mp.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    worker = context.Process(target=_worker, args=(send, candidate, tuple(members), tuple(instances), tuple(names)))
    worker.start()
    send.close()
    rows, failure = [], None
    try:
        for name in names:
            if not receive.poll(timeout):
                failure = {'error_type': 'Timeout', 'error': 'whole-instance deadline exceeded', 'failed_instance': name}
                break
            try:
                row = receive.recv()
            except EOFError:
                row = {'error_type': 'WorkerExit', 'error': 'no final result'}
            if 'error' in row:
                failure = {**row, 'failed_instance': name}
                break
            rows.append(row)
    finally:
        receive.close()
        worker.join(timeout=.05)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=.5)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=.5)
    return {'valid': failure is None, 'total_instances': len(names), 'instances': rows,
            'fitness': fmean(r['score'] for r in rows) if failure is None else None,
            'elapsed_seconds': time.monotonic()-started, **(failure or {})}
