"""Ross-style steady-state operators, with explicitly versioned adaptations."""
import copy
import math

from . import model

DEFAULTS = {
    "population_size": 40, "iterations": 500, "initial_prototypes": 16,
    "max_prototypes": 32, "initial_coordinate_std": 0.25,
    "coordinate_mutation_std": 0.1, "child_mutation_probability": 0.1,
    "block_exchange_probability": 0.1,
}


def settings(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError("all prototype search parameters must be explicit")
    for key, low, high in (("population_size", 2, 1000), ("iterations", 0, 100000),
                           ("initial_prototypes", 1, 32), ("max_prototypes", 1, 32)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("invalid search parameter " + key)
    if value["initial_prototypes"] > value["max_prototypes"]:
        raise ValueError("initial prototypes exceed bound")
    for key in ("initial_coordinate_std", "coordinate_mutation_std",
                "child_mutation_probability", "block_exchange_probability"):
        x = value[key]
        if type(x) not in (int, float) or not math.isfinite(x) or not 0 < x <= 1:
            raise ValueError("invalid search parameter " + key)
    return dict(value)


def _clip(x):
    return max(-3.0, min(3.0, x))


def block(rng, members, cfg):
    return {"center": [_clip(rng.gauss(0.5, cfg["initial_coordinate_std"]))
                       for _ in range(model.layout(members)[0])], "h": rng.randrange(members)}


def initialize(rng, members, cfg):
    return model.candidate([block(rng, members, cfg) for _ in range(cfg["initial_prototypes"])], members)


def rank(record):
    return (record["J"] if record["valid"] else math.inf, record["id"])


def _two_point(a, b, rng):
    # A shared field offset preserves field meaning despite unequal lengths.
    # Each parent independently chooses its start/end prototype indices.
    width = len(a[0]["center"]) + 1
    offset1, offset2 = rng.randrange(width), rng.randrange(width)
    block_cuts = []
    for parent in (a, b):
        first, last = sorted((rng.randrange(len(parent)), rng.randrange(len(parent))))
        block_cuts.append((first, last))
    if any(first == last for first, last in block_cuts) and offset1 > offset2:
        offset1, offset2 = offset2, offset1
    cuts = [(first * width + offset1, last * width + offset2)
            for first, last in block_cuts]
    flat = [[v for p in parent for v in p["center"] + [p["h"]]] for parent in (a, b)]
    (i, j), (k, l) = cuts
    children = (flat[0][:i] + flat[1][k:l] + flat[0][j:],
                flat[1][:k] + flat[0][i:j] + flat[1][l:])
    return tuple([{"center": values[t:t + width - 1], "h": values[t + width - 1]}
                  for t in range(0, len(values), width)] for values in children)


def _shuffle(a, b, rng, probability):
    children = [[], []]
    for source, parent in enumerate((a, b)):
        for prototype in parent:
            target = 1 - source if rng.random() < probability else source
            children[target].append(copy.deepcopy(prototype))
    return children


def _mutate(blocks, rng, members, cfg):
    if rng.random() >= cfg["child_mutation_probability"]:
        return
    kind = rng.random()
    if kind < 0.25:
        blocks.append(block(rng, members, cfg))
    elif kind < 0.5:
        del blocks[rng.randrange(len(blocks))]
    else:
        dimension = model.layout(members)[0]
        probability = 1 / (4 * (dimension + 1))
        for prototype in blocks:
            for i in range(dimension):
                if rng.random() < probability:
                    prototype["center"][i] = _clip(prototype["center"][i] + rng.gauss(0, cfg["coordinate_mutation_std"]))
            if rng.random() < probability:
                prototype["h"] = rng.randrange(members)


def offspring(population, rng, members, cfg):
    first = min(rng.sample(population, 2), key=rank)
    second = rng.choice(population)
    a, b = first["candidate"]["prototypes"], second["candidate"]["prototypes"]
    children = (_two_point(a, b, rng) if rng.random() < 0.5
                else _shuffle(a, b, rng, cfg["block_exchange_probability"]))
    result = []
    for child, original in zip(children, (a, b)):
        if not child:
            child = copy.deepcopy(original)
        _mutate(child, rng, members, cfg)
        if not 1 <= len(child) <= cfg["max_prototypes"]:
            child = copy.deepcopy(original)
        result.append(model.candidate(child, members))
    return result, [first["id"], second["id"]]
