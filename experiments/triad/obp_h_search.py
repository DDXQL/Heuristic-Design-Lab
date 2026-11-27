"""Bounded H401 generation with EoH-S-inspired complementary feedback."""

from itertools import combinations
import random

from heuristic_design.core.storage import read
from .h_selection import select


POLICY = "complementary-feedback-v1"
THEMES = (
    "Prefer small post-placement residuals, with a distinct treatment for exact fits.",
    "Preserve tight gaps by favoring larger residual capacity when appropriate.",
    "Use feasible-bin order as an explicit preference for earlier bins.",
    "Use feasible-bin order as an explicit preference for later bins.",
    "Favor residual space near the size of one more current item.",
    "Balance exact fits against residual space near twice the current item size.",
    "Avoid consuming the largest feasible capacity if a suitable alternative is available.",
    "Use the mean of the currently feasible capacities to define a preferred residual.",
    "Change the preference for tight versus loose fits depending on relative item size.",
    "Group residual sizes into bands and use bin order within a band.",
)


def enabled(config):
    return (config.get("h_build") or {}).get("generation_policy") == POLICY


def check(config):
    h = config["h_build"]
    if (h.get("generation_policy") != POLICY or config["problem"] != "obp"
            or config["method"] != "u" or config["obp_h_abi"] != "obp-vector-feasible-h-v2"
            or config["instance_count"] != 96 or config["per_candidate_attempt_cap"] != 1
            or (h["search_seed"], h["request_cap"], h["target_count"], h["selection"]) !=
                (401, 40, 10, "greedy-envelope-J-v1")):
        raise ValueError("complementary feedback requires the separate OBP H401 train96/40/10 plan")


def training_records(directory, state):
    by_key = {}
    for row in state["tasks"].values():
        if row.get("status") == "completed" and row.get("valid"):
            by_key.setdefault(row["candidate"]["key"], row)
    records = list(by_key.values())
    vectors = {}
    for row in records:
        evaluation = state["evaluations"][row["evaluation_key"]]
        scores = read(directory / evaluation["path"])["instances"]
        if len(scores) != 96:
            raise ValueError("H parent requires a full train96 score vector")
        vectors[row["id"]] = tuple(x["score"] for x in scores)
    return records, vectors


def has_pilot_diversity(directory, state):
    _, vectors = training_records(directory, state)
    return len(set(vectors.values())) >= 2


def task_context(directory, state, config, task, index):
    idea = THEMES[index % len(THEMES)]
    if index < len(THEMES):
        return {**task, "h_strategy": "themed_initialization", "h_theme": idea}, []
    records, vectors = training_records(directory, state)
    distinct_scores = {}
    for row in records:
        distinct_scores.setdefault(vectors[row["id"]], row)
    parent_candidates = list(distinct_scores.values())
    if len(parent_candidates) < 2:
        raise ValueError("complementary H generation requires at least two evaluated parents")
    pool, _ = select(parent_candidates, vectors, min(10, len(parent_candidates)), config["h_build"]["selection"])
    ranks = sorted(pool, key=lambda row: (row["J"], row["semantic_id"]))
    rng = random.Random(f"H401:{config['search_seed']}:{index}")
    if index % 2 == 0:
        def distance(pair):
            a, b = pair
            return sum(abs(x - y) for x, y in zip(vectors[a["id"]], vectors[b["id"]], strict=True))
        parents = list(max(combinations(ranks, 2), key=distance))
        strategy = "complementary_search"
    else:
        parents = rng.choices(ranks, weights=[1 / rank for rank in range(1, len(ranks) + 1)])
        strategy = "local_search"
    return {**task, "h_strategy": strategy, "h_theme": idea}, [
        {"id": row["semantic_id"], "candidate": row["candidate"], "fitness": -row["J"]}
        for row in parents
    ]


def prompt_context(task, parents):
    text = [
        "Generate one online bin-packing rule within the exact interface above.",
        f"Scoring direction for this slot: {task['h_theme']}",
        "Aim to change the preferred bin on at least one legal input. Renaming variables, "
        "adding a constant to all scores or applying a monotone rescaling does not yield a new choice.",
    ]
    if parents:
        text.append("The two parent rules differ in their measured performance across training instances. "
                    "Explore a different strategy that could complement them."
                    if task["h_strategy"] == "complementary_search" else
                    "Refine the parent rule while preserving its useful behavior. Make a substantive scoring change.")
        for row in parents:
            text.append(f"Parent {row['id']} (mean train gap {-row['fitness']:.8g}):\n{row['candidate']['code']}")
    return "\n".join(text)
