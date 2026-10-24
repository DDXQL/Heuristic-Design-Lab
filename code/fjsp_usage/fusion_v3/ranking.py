"""Exact midrank Borda, plus rational two-member WS representability diagnosis."""
from fractions import Fraction
import math
import numbers


def borda_twice(values):
    """2*B(a) = 2*#strictly-lower + #equal - 1; high scores are preferred.

    Input order never breaks per-column ties. Summing these integer points is
    argmax-equivalent to mean percentile midranks. One action -> zero.
    """
    if not values or any(isinstance(x, bool) or not isinstance(x, numbers.Real)
                         or not math.isfinite(x) for x in values):
        raise ValueError('nonempty finite real score column required')
    order = sorted(range(len(values)), key=values.__getitem__)
    points = [0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        twice_midrank = start + end - 1
        for i in order[start:end]:
            points[i] = twice_midrank
        start = end
    return tuple(points)


def borda_scores(columns, support):
    if len(support) != 2 or len(set(support)) != 2:
        raise ValueError('exactly two distinct members required')
    ranks = {i: borda_twice(columns[i]) for i in support}
    n = len(ranks[support[0]])
    if any(len(ranks[i]) != n for i in support):
        raise ValueError('aligned action columns required')
    return tuple(sum(ranks[i][a] for i in support) for a in range(n)), ranks


def ws_certificate(raw, normalized, support, target):
    """Exact rational feasibility on stored float columns, stable FIRST argmax.

    This certifies ideal real linear combinations of the stored normalized
    floats; it does not equate real arithmetic with every IEEE implementation.
    Endpoints use the actual raw SELECT policy, preserving V1's single-support
    bypass. Interior witnesses are separately checked through the V1 combiner.
    """
    from fjsp_usage.usage_v2.execution import combine_scores
    n = len(raw[support[0]])
    for index, member in enumerate(support):
        if max(range(n), key=lambda a: raw[member][a]) == target:
            return {'status': 'raw_endpoint_witness', 'alpha': 1. if index == 0 else 0.}
    x = [Fraction(v) for v in normalized[support[0]]]
    y = [Fraction(v) for v in normalized[support[1]]]
    low, high = Fraction(0), Fraction(1)
    low_open = high_open = True
    low_action = high_action = None
    for a in range(n):
        if a == target:
            continue
        intercept = y[target] - y[a]
        slope = x[target] - x[a] - intercept
        strict = a < target
        if slope == 0:
            if intercept < 0 or intercept == 0 and strict:
                return {'status': 'outside_real_linear_WS', 'constant_competitor': a,
                        'target': target, 'exact_intercept': str(intercept)}
            continue
        bound = -intercept / slope
        if slope > 0:
            if bound > low:
                low, low_open, low_action = bound, strict, a
            elif bound == low:
                low_open |= strict
        else:
            if bound < high:
                high, high_open, high_action = bound, strict, a
            elif bound == high:
                high_open |= strict
        if low > high or low == high and (low_open or high_open):
            return {'status': 'outside_real_linear_WS', 'target': target,
                    'low': str(low), 'high': str(high), 'low_open': low_open, 'high_open': high_open,
                    'low_competitor': low_action, 'high_competitor': high_action}
    alpha = float((low + high)/2)
    weights = tuple(alpha if i == support[0] else 1-alpha if i == support[1] else 0.
                    for i in range(max(support)+1))
    scores, _ = combine_scores(raw, weights, support)
    actual = max(range(n), key=scores.__getitem__)
    return {'status': 'interior_IEEE_witness' if actual == target else 'real_feasible_IEEE_witness_not_matched',
            'alpha': alpha, 'actual_action': actual, 'low': str(low), 'high': str(high)}
