"""Handwritten H, synthetic development instances and real offline route solves.

Default fixtures are engineering examples, not the frozen research H0-H9.
Explicit train snapshots may also be decoded; no held-out split routing is offered.
"""
from dataclasses import asdict
import time
import numpy as np

from heuristic_design.core.storage import digest
from heuristic_design.core import routing


def members(problem):
    if problem == 'fjsp':
        from fjsp_usage.research.candidates import H_ARGS, validate_code
        expressions = ('-earliest_finish', '-processing_time', 'remaining_work')
        return [asdict(validate_code('def priority('+', '.join(H_ARGS)+'):\n    return '+x+'\n',
                                     description='Handwritten synthetic fixture: '+x, kind='h')) for x in expressions]
    if problem == 'tsp':
        from .tsp.candidates import H_ARGS, validate
        expressions = ('-distance_current', 'distance_current', '-distance_current + 0.3 * distance_start')
        return [asdict(validate('def priority('+', '.join(H_ARGS)+'):\n    return '+x+'\n',
                                description='Handwritten synthetic fixture: '+x, kind='h', member_count=3)) for x in expressions]
    raise ValueError('unknown fixture problem')


def compile_members(problem, rows):
    if problem == 'fjsp':
        from fjsp_usage.research.candidates import validate_code, compile_candidate
        candidates = [validate_code(r['code'], description=r['description'], kind='h') for r in rows]
        if any(c.key != r['key'] or r['kind'] != 'h' for c,r in zip(candidates, rows)):
            raise ValueError('frozen H identity changed')
        return [compile_candidate(c) for c in candidates]
    from .tsp.candidates import checked, compile_candidate
    return [compile_candidate(checked(r, len(rows)), len(rows)) for r in rows]


def instances(problem, *, size=12, count=2, seed=501):
    rng = np.random.default_rng(seed)
    rows = []
    for index in range(count):
        if problem == 'fjsp':
            machines, jobs = 4, []
            for j in range(max(2, size//3)):
                job = []
                for o in range(3):
                    choices = sorted(int(x) for x in rng.choice(machines, size=2, replace=False))
                    job.append([[m, int(rng.integers(1,21))] for m in choices])
                jobs.append(job)
            value = {'machines': machines, 'jobs': jobs}
        elif problem == 'tsp':
            value = {'coordinates': rng.random((max(3,size),2)).tolist()}
        else:
            raise ValueError('unknown fixture problem')
        rows.append({'file': f'synthetic-{problem}-{seed}-{index}', 'split': 'synthetic-development',
                     'value': value, 'sha256': digest(value)})
    return rows


def solve(problem, instance, h_rows, candidate, *, window=10, enabled_groups=None, trace=True):
    from heuristic_design.core.constructive_state import GROUPS
    from .fjsp.routing import construct as fjsp
    from .tsp.routing import construct as tsp
    hs = compile_members(problem, h_rows)
    u = routing.compile_candidate(routing.checked(candidate,len(hs)),len(hs))
    obj = decode_instance(problem,instance)
    started = time.perf_counter()
    kwargs = dict(window=window, enabled_groups=tuple(GROUPS) if enabled_groups is None else enabled_groups, trace=trace)
    if problem == 'fjsp':
        result = fjsp(obj, hs, u, **kwargs)
        solution = asdict(result.schedule)
    else:
        result = tsp(obj,hs,u,**kwargs)
        solution = {'tour': list(result.tour), 'length': result.length}
    elapsed = time.perf_counter() - started
    return {'file': instance['file'], 'score': result.score, 'solution': solution,
            'trace': list(result.trace), 'h_calls': list(result.h_calls),
            **({'member_sequence': list(result.member_sequence)} if problem == 'fjsp' else {}),
            'solve_seconds': elapsed, 'observation_seconds': result.observation_seconds}


def decode_instance(problem,instance):
    from .tsp.solver import distances
    from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation
    spec=instance['value']
    if instance['sha256'] != digest(spec) or instance['split'] not in ('synthetic-development','train'):
        raise ValueError('synthetic fixture identity/split mismatch')
    if problem=='fjsp':
        # Do not silently round or coerce incompatible processing times/IDs.
        return FJSPInstance(instance['file'],spec['machines'],tuple(tuple(
            Operation(tuple((m,p) for m,p in op)) for op in job) for job in spec['jobs']))
    if problem=='tsp':return distances(spec['coordinates'])
    raise ValueError('unknown instance problem')


def precheck_instances(problem,data):
    """Policy-independent compatibility and objective references, before P0."""
    from .fjsp.common_state import precheck as fjsp_check
    from .tsp.common_state import precheck as tsp_check
    from .tsp.solver import nearest_neighbor
    from fjsp_usage.offline_v2 import lower_bound_v5
    references=[]
    names=set()
    for spec in data:
        if spec['file'] in names:raise ValueError('duplicate instance name')
        names.add(spec['file'])
        obj=decode_instance(problem,spec)
        if problem=='fjsp':
            fjsp_check(obj);value=lower_bound_v5(obj)
        else:
            tsp_check(obj);value=nearest_neighbor(obj)[1]
        references.append({'file':spec['file'],'reference':value,'rule':'LB_v5' if problem=='fjsp' else 'NN'})
    return references


def sample_policy(members_count):
    code = '''def use_heuristics(state):
    if state["availability"]["previous_h_token"]:
        if state["construction_progress"] > 0.6:
            return 1
    return 0
'''
    return asdict(routing.validate(code, 'Handwritten progress router; no learned quality claim', members_count))
