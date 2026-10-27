def fuse_scores(columns, weights, support, operator):
    if operator not in ('SELECT',) + OPERATORS:
        raise UsageOutputError('unknown fusion operator')
    if not support or len(support) > 2 or any(i not in columns for i in support):
        raise UsageOutputError('one/two available member columns required')
    length = len(columns[support[0]])
    if not length or any(len(columns[i]) != length for i in support):
        raise NormalizationError('nonempty aligned action columns required')
    if any(isinstance(v, bool) or not isinstance(v, numbers.Real) or not math.isfinite(v)
           for i in support for v in columns[i]):
        raise NormalizationError('finite real H columns required')
    if (operator == 'SELECT' and len(support) != 1 or
            operator in ('MAX', 'MIN') and len(support) != 2):
        raise UsageOutputError('operator/support mismatch')
    if operator == 'SELECT':
        return combine_scores(columns, weights, support)
    if any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights):
        raise UsageOutputError('finite nonnegative normalized weights required')
    if (any(i >= len(weights) or weights[i] <= 0 for i in support)
            or any(w != 0 for i, w in enumerate(weights) if i not in support)
            or not math.isclose(math.fsum(weights), 1, rel_tol=0, abs_tol=1e-15)):
        raise NormalizationError('weights must retain support and unit sum')
    scores, info = combine_scores(columns, weights, support)
    if operator in ('MAX', 'MIN'):
        if weights[support[0]] != weights[support[1]]:
            raise UsageOutputError('unweighted extrema require equal indicators')
        operation = max if operator == 'MAX' else min
        scores = tuple(operation(info['normalized'][i][a] for i in support)
                       for a in range(length))
    return scores, info
