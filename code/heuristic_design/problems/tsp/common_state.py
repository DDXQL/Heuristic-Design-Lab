"""TSP common observation: open-path cost, optional edges only."""
import math
import numpy as np
from heuristic_design.core.constructive_state import observe, GROUPS


def precheck(d):
    d = np.asarray(d)
    if (d.ndim != 2 or d.shape[0] != d.shape[1] or len(d) < 3
            or not np.isfinite(d).all() or (d < 0).any()
            or not np.array_equal(d, d.T) or np.any(np.diag(d) != 0)):
        raise ValueError('finite symmetric nonnegative TSP matrix with zero diagonal required')
    scale = len(d) * float(np.max(d))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('zero/nonfinite n*Dmax; reject before policy evaluation')
    return scale


def extract(d, tour, remaining, partial, history, scale, enabled_groups=tuple(GROUPS)):
    return observe('tsp', history=history, action_bound=len(d)-1,
                   partial_cost=partial, scale=scale,
                   action_deltas=(float(d[tour[-1], j]) for j in remaining),
                   enabled_groups=enabled_groups)
