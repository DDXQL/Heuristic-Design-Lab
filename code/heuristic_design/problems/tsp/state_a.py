"""Scheme A sensors for an open TSP path; no completion or H calls."""
from heuristic_design.core.state_a import observe
from .common_state import precheck


class Sensors:
    def __init__(self, distances):
        precheck(distances)
        self.d = distances
        self.size = len(distances)
        self.dmax = max(float(x) for row in distances for x in row)

    def extract(self, tour, remaining, history):
        if (history.decisions != self.size - 1 or history.count != len(tour) - 1
                or not tour or tour[0] != 0 or len(set(tour)) != len(tour)
                or len(set(remaining)) != len(remaining)
                or set(tour) & set(remaining) or set(tour) | set(remaining) != set(range(self.size))):
            raise ValueError('TSP state/history mismatch')
        degree = [0] * self.size
        for a, b in zip(tour, tour[1:]):
            degree[a] += 1
            degree[b] += 1
        return observe('tsp', history=history,
            demands=(min(float(self.d[i, j]) for j in (*remaining, 0) if j != i) / self.dmax
                     for i in remaining),
            commitments=(k / 2 for k in degree),
            action_deltas=(float(self.d[tour[-1], j]) / self.dmax for j in remaining))

    def delta(self, current, chosen):
        return float(self.d[current, chosen]) / self.dmax
