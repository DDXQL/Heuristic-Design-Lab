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
