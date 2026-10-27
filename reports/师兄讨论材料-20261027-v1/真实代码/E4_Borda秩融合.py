def borda_scores(columns, support):
    if len(support) != 2 or len(set(support)) != 2:
        raise ValueError('exactly two distinct members required')
    ranks = {i: borda_twice(columns[i]) for i in support}
    n = len(ranks[support[0]])
    if any(len(ranks[i]) != n for i in support):
        raise ValueError('aligned action columns required')
    return tuple(sum(ranks[i][a] for i in support) for a in range(n)), ranks
