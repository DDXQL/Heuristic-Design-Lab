"""Killable per-instance execution of validated numerical candidates.

The AST gate blocks resource access; this is not a general Python/OS sandbox.
Each full instance is repeated to detect stateful/nondeterministic behaviour.
"""

import multiprocessing as mp
from statistics import fmean
import time

from fjsp_usage.offline_v2 import lower_bound_v5
from llm4ad.task.optimization.fjsp_set import construct_schedule
from .candidates import Candidate, compile_candidate
from .scheduler import construct_usage_schedule


def _worker(connection, candidate, members, instances, names):
    try:
        function = compile_candidate(candidate)
        rules = tuple(compile_candidate(member) for member in members)
        for name, instance in zip(names, instances):
            if candidate.kind == 'U':
                first = construct_usage_schedule(instance, rules, function)
                second = construct_usage_schedule(instance, rules, function)
                if first != second:
                    raise ValueError('nondeterministic result')
                schedule, bound, score = first.schedule, first.lower_bound, first.score
            else:
                schedule = construct_schedule(instance, function)
                if schedule != construct_schedule(instance, function):
                    raise ValueError('nondeterministic result')
                bound = lower_bound_v5(instance)
                score = -schedule.makespan / bound
            connection.send({'file': name, 'makespan': schedule.makespan,
                             'lower_bound': bound, 'score': score})
    except BaseException as exc:
        connection.send({'error_type': type(exc).__name__, 'error': str(exc)[:500]})
    finally:
        connection.close()


def evaluate(candidate: Candidate, members, instances, names, *, timeout=2.0):
    if not instances or len(instances) != len(names) or timeout <= 0:
        raise ValueError('nonempty aligned train batch and positive timeout required')
    started = time.monotonic()
    context = mp.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(send, candidate, tuple(members),
                                                    tuple(instances), tuple(names)))
    process.start()
    send.close()
    records, failure = [], None
    try:
        for name in names:
            if not receive.poll(timeout):
                failure = {'error_type': 'Timeout', 'error': 'per-instance deadline exceeded',
                           'failed_instance': name}
                break
            try:
                message = receive.recv()
            except EOFError:
                message = {'error_type': 'WorkerExit', 'error': 'worker exited without result'}
            if 'error' in message:
                failure = {**message, 'failed_instance': name}
                break
            records.append(message)
    finally:
        receive.close()
        process.join(timeout=0.05)
        if process.is_alive():
            process.terminate()
            process.join(timeout=0.5)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.5)
    return {'valid': failure is None, 'total_instances': len(instances), 'instances': records,
            'fitness': fmean(row['score'] for row in records) if failure is None else None,
            'elapsed_seconds': time.monotonic() - started, **(failure or {})}
