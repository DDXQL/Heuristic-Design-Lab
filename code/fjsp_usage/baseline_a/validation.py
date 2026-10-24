"""Result and ledger validation, including historical two-solve cache levels."""
import math
from statistics import fmean
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result
from .policies import specs


def validate_result(result,instances,level):
    check_result(result,[r['file'] for r in instances])
    rows=result['instances']
    if len(rows)>len(instances) or [r['file'] for r in rows]!=[r['file'] for r in instances[:len(rows)]]:
        raise ValueError('ordered success prefix required')
    for row,expected in zip(rows,instances):
        if (type(row.get('makespan')) is not int or row['makespan']<=0 or row['lower_bound']!=expected['LB']
            or row['score']!=-row['makespan']/expected['LB'] or row['feasible'] is not True):
            raise ValueError('instance/LB/Fitness/feasibility mismatch')
        for key in ('single_solve_seconds','deterministic_recheck_seconds'):
            if type(row.get(key)) not in (float,int) or not math.isfinite(row[key]) or row[key]<0:
                raise ValueError('missing two-solve timing evidence')
        if level=='legacy_single':
            h=row.get('deterministic_schedule_sha256')
            if not isinstance(h,str) or len(h)!=64:raise ValueError('missing native full-result recheck hash')
        elif level in ('legacy_pair','modern'):
            if (row.get('captured_solves')!=2 or digest(row['physical_schedule'])!=row['physical_schedule_sha256']
                or row['physical_schedule_sha256']!=row['recheck_physical_schedule_sha256']
                or row['physical_schedule']['makespan']!=row['makespan']):raise ValueError('physical two-solve mismatch')
            second=row.get('recheck_h_calls',row.get('deterministic_recheck_h_calls'))
            if row.get('single_h_calls')!=second:raise ValueError('H call recheck mismatch')
            if level=='modern' and any(row['network_guard'].values()):raise ValueError('forbidden access attempted')
        else:raise ValueError('unknown evidence level')
    if result['valid'] and result['fitness']!=fmean(r['score'] for r in rows):raise ValueError('full mean mismatch')


def validate_ledger(state,protocol,read,sha,directory):
    if state['protocol_sha256']!=sha(directory/'Protocol.json'):raise ValueError('ledger protocol mismatch')
    definitions={s['id']:s for s in specs()};cache=protocol['cache'];new=0
    if not set(state['strategies'])<=set(definitions):raise ValueError('unknown strategy ledger entry')
    for identifier,row in state['strategies'].items():
        if row['status']!='completed':raise ValueError('unknown reservation; never automatically repeat')
        if identifier in cache:
            if row.get('origin')!='cache' or row['reserved_evaluations']!=0 or row['reserved_solve_passes']!=0:
                raise ValueError('cache ledger budget mismatch')
            if (row['result_path'],row['result_sha256'])!=(cache[identifier]['result_path'],cache[identifier]['sha256']):
                raise ValueError('cache result provenance mismatch')
        else:
            if row.get('origin')!='new' or (row['reserved_evaluations'],row['reserved_solve_passes'])!=(21,42):
                raise ValueError('new strategy reservation mismatch')
            new+=21
        path=directory/row['result_path']
        if not path.resolve().is_relative_to(directory.resolve()) or sha(path)!=row['result_sha256']:
            raise ValueError('saved result hash/path mismatch')
        result=read(path)
        if result['valid']!=row['valid']:raise ValueError('ledger validity mismatch')
        validate_result(result,protocol['instances'],cache[identifier]['level'] if identifier in cache else 'modern')
    if not set(cache)<=set(state['strategies']):raise ValueError('missing cache ledger entries')
    if new>protocol['new_evaluation_cap'] or 2*new>protocol['new_solve_pass_cap']:
        raise ValueError('budget exceeded')
    return new
