"""Exact arithmetic shortcut for the bound preset-N integer OBP state."""

from functools import lru_cache
from statistics import _float_sqrt_of_frac

import numpy as np

from heuristic_design.core import state_a as base, state_a_v3 as public


@lru_cache(maxsize=8)
def load_ratios(capacity):
    # These are ratios of the originally rounded binary64 load fractions.
    ratios = [(load / capacity).as_integer_ratio() for load in range(capacity + 1)]
    scale = max(d for _, d in ratios)
    first = [n * (scale // d) for n, d in ratios]
    return scale, first, [value * value for value in first]


def commitment_pair(frequencies, count, capacity):
    if not count:
        return None, None
    scale, loads, squares = load_ratios(capacity)
    first = second = 0
    for load in np.flatnonzero(frequencies[1:]).tolist():
        index = load + 1
        frequency = int(frequencies[index])
        first += frequency * loads[index]
        second += frequency * squares[index]
    return (
        (first / scale) / count,
        _float_sqrt_of_frac(count * second - first * first, (count * scale) ** 2),
    )


def extract(current_item, used, capacity, history):
    """Receive loads maintained by the integer solver and return the same packet."""
    remaining = capacity - used
    index = np.flatnonzero(remaining >= current_item)
    actions = tuple(index.tolist())
    n_actions = len(actions)
    frequencies = np.bincount(used)
    empty = int(frequencies[0]) if len(frequencies) else 0
    opened = len(used) - empty
    if (not n_actions or opened > history.count
            or (history.count == 0) != (opened == 0)):
        raise ValueError("invalid preset-N action domain or opened-bin history")
    recent = tuple(delta for _, delta in history.recent)
    packet = base._assemble_packet("obp", base.schema_id("obp"), history, (
        history.count / history.decisions, n_actions,
        current_item / capacity, 0.0,
        *commitment_pair(frequencies, opened, capacity),
        empty / n_actions, _float_sqrt_of_frac(empty * (n_actions - empty), n_actions ** 2),
        *base._pair(recent),
    ))
    return public.extend_packet(packet, history), actions, tuple(remaining[index].tolist())
