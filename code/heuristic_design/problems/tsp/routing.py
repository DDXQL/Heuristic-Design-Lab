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
    member_sequence: tuple = ()


@dataclass(frozen=True, kw_only=True)
class StateAResult(RouteResult):
    reference: float
    score_direction: str = 'min'
    state_schema: str = 'common-state-a-v2-tsp'


def construct(d, heuristics, usage, *, window=10, enabled_groups=tuple(GROUPS), trace=True,
              state_schema=None, reference=None):
    sensors = None
    if state_schema is not None:
        if state_schema == 'common-state-a-v3-tsp':
            from heuristic_design.core import state_a_v3 as state_a
            from .state_a_v3 import Sensors
        else:
            from heuristic_design.core import state_a
            from .state_a import Sensors
        if state_schema != state_a.schema_id('tsp') or tuple(enabled_groups) != tuple(GROUPS):
            raise ValueError('explicit full scheme-A schema required; no feature disabling')
        if type(window) is not int or window != state_a.WINDOW:
            raise ValueError('scheme A freezes window=10')
        state_a.score_final_cost(0, reference)  # fail before any U/H or solve if reference absent
        sensors = Sensors(d)
    elif reference is not None:
        raise ValueError('legacy score cannot accept a scheme-A reference')
    scale = precheck(d)
    members = tuple(heuristics)
    if not members or not all(callable(h) for h in members) or not callable(usage):
        raise ValueError('nonempty callable H and U required')
    remaining, tour = list(range(1, len(d))), [0]
    history_type = state_a.History if sensors is not None else History
    history = history_type(len(d)-1, len(members), window)
    rows, calls, partial, observation = [], [0]*len(members), 0., 0.
    selected_members = []
    while remaining:
        current, progress = tour[-1], (len(tour)-1)/(len(d)-1)
        started = time.perf_counter()
        packet = (sensors.extract(tour, remaining, history) if sensors is not None
                  else extract(d, tour, remaining, partial, history, scale, enabled_groups))
        observation += time.perf_counter() - started
        member = route_token(usage(packet), len(members))
        selected_members.append(member)
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
        delta = sensors.delta(current, city) if sensors is not None else cost / scale
        if trace:
            rows.append({'step': len(tour)-1, 'state': plain(packet), 'member_id': member,
                         'remaining': remaining[:], 'action_features': inputs,
                         'raw_scores': scores, 'chosen': city, 'committed_delta': delta,
                         'h_calls': {member: len(remaining)}})
        tour.append(city)
        remaining.pop(index)
        partial += cost
        history.commit(member, delta)
    tour.append(0)
    length = tour_length(d, tour)
    if sensors is not None:
        return StateAResult(tuple(tour), length, state_a.score_final_cost(length, reference),
                            tuple(rows), tuple(calls), observation, tuple(selected_members), reference=reference, state_schema=state_schema)
    return RouteResult(tuple(tour), length, -length/nearest_neighbor(d)[1], tuple(rows), tuple(calls), observation,
                       tuple(selected_members))


def construct_state_a(d, heuristics, usage, *, reference, trace=True):
    """Reference must be the caller's frozen LKH length. No reference solve here."""
    from heuristic_design.core.state_a import schema_id
    return construct(d, heuristics, usage, trace=trace,
                     state_schema=schema_id('tsp'), reference=reference)


def construct_state_a_v3(d, heuristics, usage, *, reference, trace=True):
    from heuristic_design.core.state_a_v3 import schema_id
    return construct(d, heuristics, usage, trace=trace,
                     state_schema=schema_id('tsp'), reference=reference)
