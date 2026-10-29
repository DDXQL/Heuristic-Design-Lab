"""Pure-route TSP constructor; optional decisions exclude forced closure."""
from dataclasses import dataclass
import math
import time
import numpy as np

from heuristic_design.core.constructive_state import History, GROUPS, plain
from heuristic_design.core.routing import route_token
from .solver import SCALE, tour_length, nearest_neighbor
from .common_state import precheck, extract


@dataclass(frozen=True)
class RouteResult:
    tour: tuple
    length: float
    score: float
    trace: tuple
    h_calls: tuple
    observation_seconds: float


def construct(d, heuristics, usage, *, window=10, enabled_groups=tuple(GROUPS), trace=True):
    scale = precheck(d)
    members = tuple(heuristics)
    if not members or not all(callable(h) for h in members) or not callable(usage):
        raise ValueError('nonempty callable H and U required')
    remaining, tour = list(range(1, len(d))), [0]
    history = History(len(d)-1, len(members), window)
    rows, calls, partial, observation = [], [0]*len(members), 0., 0.
    while remaining:
        current, progress = tour[-1], (len(tour)-1)/(len(d)-1)
        started = time.perf_counter()
        packet = extract(d, tour, remaining, partial, history, scale, enabled_groups)
        observation += time.perf_counter() - started
        member = route_token(usage(packet), len(members))
        inputs, scores = [], []
        for city in remaining:
            ds = [float(d[city,j])/SCALE for j in remaining if j != city]
            args = (float(d[current,city])/SCALE, float(d[city,0])/SCALE,
                    math.fsum(ds)/len(ds) if ds else 0., min(ds) if ds else 0., progress)
            inputs.append(args)
            value = members[member](*args)
            calls[member] += 1
            if type(value) not in (int,float) or not math.isfinite(value) or abs(value) > 1e100:
                raise ValueError('finite bounded scalar H required')
            scores.append(float(value))
        index = max(range(len(remaining)), key=lambda j: (scores[j], -remaining[j]))
        city = remaining[index]
        cost = float(d[current,city])
        if trace:
            rows.append({'step': len(tour)-1, 'state': plain(packet), 'member_id': member,
                         'remaining': remaining[:], 'action_features': inputs,
                         'raw_scores': scores, 'chosen': city, 'committed_delta': cost/scale,
                         'h_calls': {member: len(remaining)}})
        tour.append(city)
        remaining.pop(index)
        partial += cost
        history.commit(member, cost/scale)
    tour.append(0)
    length = tour_length(d, tour)
    return RouteResult(tuple(tour), length, -length/nearest_neighbor(d)[1], tuple(rows), tuple(calls), observation)
