"""Rank selection and generation survival; fitness is always maximized."""

def ranked(population):
    return sorted(population, key=lambda row: (-row['fitness'], row['id']))


def _tuple_tree(value):
    return tuple(_tuple_tree(item) for item in value) if isinstance(value, list) else value


def select_parents(population, count, rng):
    pool = ranked(population)
    if count > len(pool):
        raise ValueError('not enough distinct parents')
    # Weights use ranks in the ORIGINAL frozen generation. Deleting selected
    # parents must not recompute ranks/N for those that remain.
    weights = [1 / (len(pool) + rank) for rank in range(len(pool))]
    chosen = []
    for _ in range(count):
        index = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        chosen.append(pool.pop(index))
        weights.pop(index)
    return chosen


def survive(population, children, size):
    return ranked(population + children)[:size]


def survive_behavior_first(population, children, size):
    """Best representative per observed behavior, then ranked duplicate fill.

    Inputs are already certified complete evaluations. Exact behavior identity
    is supplied by the existing evaluator; this function never evaluates U.
    """
    pool = ranked(population + children)
    if type(size) is not int or size < 1 or len(pool) < size:
        raise ValueError('positive size and enough certified candidates required')
    if len({r['id'] for r in pool}) != len(pool):
        raise ValueError('distinct candidate IDs required')
    if any(not isinstance(r.get('behavior_sha256'), str) or not r['behavior_sha256'] for r in pool):
        raise ValueError('complete behavior identity required')
    representatives = []
    seen = set()
    for row in pool:
        key = row['behavior_sha256']
        if key not in seen:
            representatives.append(row)
            seen.add(key)
    selected = representatives[:size]
    ids = {r['id'] for r in selected}
    selected += [r for r in pool if r['id'] not in ids][:size-len(selected)]
    return ranked(selected)
