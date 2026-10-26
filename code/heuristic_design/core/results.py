"""Common result envelope. Problem adapters validate feasibility/objectives."""
import math
from statistics import fmean


def validate_complete(result, instances):
    rows=result['instances']
    if result['total_instances']!=len(instances) or len(rows)>len(instances):
        raise ValueError('declared instance count differs')
    if [r['file'] for r in rows]!=[r['file'] for r in instances[:len(rows)]]:
        raise ValueError('ordered instance prefix required')
    if result['valid']:
        if not rows or len(rows)!=len(instances) or not all(math.isfinite(r['score']) for r in rows):
            raise ValueError('complete finite scores required')
        if result['fitness']!=fmean(r['score'] for r in rows):raise ValueError('mean fitness mismatch')
    elif result['fitness'] is not None:raise ValueError('invalid candidate must have null fitness')
