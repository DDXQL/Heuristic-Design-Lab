"""Independent prototype search using frozen U inputs and the shared evaluator.

There is deliberately no transport, credential, scheduler, or automatic holdout
path. An interrupted evaluation is never silently replayed on resume.
"""
from contextlib import contextmanager
import copy
import csv
import fcntl
import json
import math
from pathlib import Path
import random
import statistics
import time

from heuristic_design.core import state_a_v3 as state
from heuristic_design.core.storage import digest, read, sha, write
from experiments.triad import evaluation, problems
from . import genetics, model

ROOT = Path(__file__).resolve().parents[2]
VERSION = "prototype-hh-search-v1"


def sources():
    paths = list((ROOT / "code").rglob("*.py"))
    paths += list((ROOT / "experiments/triad").glob("*.py"))
    paths += list(Path(__file__).parent.glob("*.py"))
    paths += [ROOT / "tools/prototype_hh.py"]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def verify_sources(bound):
    if any(not (ROOT / name).is_file() or sha(ROOT / name) != key for name, key in bound.items()):
        raise ValueError("source changed; restore the bound release before resuming")


def _tuple(value):
    return tuple(_tuple(x) for x in value) if isinstance(value, list) else value


def _path(value):
    return (ROOT / value).resolve()


def scientific_sources(problem):
    names = ["code/heuristic_design/core/" + n + ".py" for n in
             ("state_a", "state_a_v3", "constructive_state", "lifecycle")]
    names += ["code/heuristic_design/problems/" + problem + "/" + n + ".py"
              for n in ("routing", "state_a", "state_a_v3", "common_state", "solver")
              if (ROOT / "code/heuristic_design/problems" / problem / (n + ".py")).is_file()]
    names.append("code/heuristic_design/problems/routing_fixtures.py")
    if problem == "fjsp":
        names += ["code/fjsp_usage/offline_v2.py"]
        names += [str(p.relative_to(ROOT)) for p in sorted(
            (ROOT / "code/llm4ad/task/optimization/fjsp_set").glob("*.py"))]
    return {name: sha(ROOT / name) for name in names}


def load_config(path):
    cfg = read(path)
    if set(cfg) != {"version", "problem", "seeds", "source_u_protocol", "source_u_protocol_sha256", "search"}:
        raise ValueError("explicit prototype configuration fields required")
    if cfg["version"] != VERSION or cfg["problem"] not in state.PROBLEMS or cfg["seeds"] != [501, 502, 503]:
        raise ValueError("prototype protocol/problem/three search seeds mismatch")
    genetics.settings(cfg["search"])
    return cfg


def _training_snapshot(cfg):
    source = _path(cfg["source_u_protocol"])
    if sha(source) != cfg["source_u_protocol_sha256"]:
        raise ValueError("source U protocol hash mismatch")
    p = read(source)
    c, data, refs, hs = p["config"], p["instances"], p["references"], p["members"]
    problem = cfg["problem"]
    if (p["run_kind"] != "u" or c["method"] != "u" or c["problem"] != problem or c["mode"] != "real"
            or c.get("evaluation_mode") != "solve" or c["instance_timeout_seconds"] != 30
            or p["state_schema"] != state.schema_id(problem)):
        raise ValueError("a real scheme-A-v3 U training protocol with T30 is required")
    physical_sources = scientific_sources(problem)
    for name, key in physical_sources.items():
        if p["source_files"].get(name) != key:
            raise ValueError("source U state/solver/T30 implementation differs: " + name)
    if not data or len(data) != c["instance_count"] or len(data) != len(refs) or len(hs) != 10:
        raise ValueError("complete training rows/references and frozen 10H required")
    if len({x["file"] for x in data}) != len(data) or len({h["key"] for h in hs}) != len(hs):
        raise ValueError("duplicate training names or H keys")
    for spec, ref in zip(data, refs):
        if (spec["split"] != "train" or digest(spec["value"]) != spec["sha256"]
                or spec["file"] != ref["file"] or type(ref["reference"]) not in (int, float)
                or not math.isfinite(ref["reference"]) or ref["reference"] <= 0):
            raise ValueError("training snapshot/reference mismatch")
    for h in hs:
        problems.checked_h(problem, h)
    if problem == "fjsp":
        expected = problems.fixtures.precheck_instances(problem, data)
        if expected != refs:
            raise ValueError("FJSP LB_v5 reference differs from U")
    elif problem == "tsp":
        from heuristic_design.problems.tsp.solver import distances, tour_length
        for spec, ref in zip(data, refs):
            if (ref["source"] != "LKH" or ref["instance_sha256"] != spec["sha256"]
                    or not math.isclose(tour_length(distances(spec["value"]["coordinates"]), ref["tour"]),
                                        ref["reference"], rel_tol=1e-12, abs_tol=1e-12)):
                raise ValueError("fixed U LKH reference differs")
    else:
        if (c["obp_actions"] != "preallocated_empty_bins" or c["obp_h_abi"] != "obp-vector-feasible-h-v2"
                or any("N" not in spec["value"] for spec in data)):
            raise ValueError("current formal OBP preset-N/vector-H protocol required")
        if p.get("obp_contract_sha256") != digest(problems.obp_contract(c)):
            raise ValueError("source OBP action/H/reference contract mismatch")
        for spec, ref in zip(data, refs):
            expected = {"file": spec["file"], **problems.obp_reference_details(spec["value"], c["obp_bound"])}
            if expected != ref:
                raise ValueError("OBP R_code reference differs from U")
        delivery = copy.deepcopy(c["state_delivery"])
        if Path(delivery["file"]).name != "obp_state_preset.py":
            raise ValueError("unsupported OBP state provider; explicit adapter review required")
        delivery["file"] = str(ROOT / "experiments/triad/obp_state_preset.py")
        c = {**c, "state_delivery": delivery}
        problems.state_provider(c)  # imports/verifies the delivered state; no solve
    # Shared solver inputs are embedded in the authenticated U protocol. This
    # preserves exact order and permits a relocated release without old paths.
    context = {"config": {**c, "method": "prototype_hh", "evaluation_concurrency": 1,
                           "api_concurrency": 0, "real_requests_authorized": False},
               "instances": data, "references": refs, "members": hs}
    context["shared_H_cost"] = p.get("source_cost")
    binding = {"source_u_protocol_sha256": sha(source), "problem": problem,
               "state_spec_sha256": state.SPEC_SHA256, "H_keys": [h["key"] for h in hs],
               "training_instance_contents": [r["sha256"] for r in data],
               "shared_scientific_sources": physical_sources,
               "source_problem_adapter_sha256": p["source_files"].get("experiments/triad/problems.py"),
               "training_instances_sha256": digest(data), "training_references_sha256": digest(refs)}
    return context, binding


def check(path):
    cfg = load_config(path)
    pending = []
    for key in ("source_u_protocol", "source_u_protocol_sha256"):
        if not cfg[key]:
            pending.append(key)
    if not pending and not _path(cfg["source_u_protocol"]).is_file():
        pending.append("source_u_protocol file missing")
    context = binding = None
    if not pending:
        context, binding = _training_snapshot(cfg)
    slots = cfg["search"]["population_size"] + 2 * cfg["search"]["iterations"]
    return cfg, context, binding, {"pending": pending, "problem": cfg["problem"], "seeds": cfg["seeds"],
        "logical_candidate_slots_per_seed": slots, "training_instances": len(context["instances"]) if context else None,
        "max_instance_solve_passes_per_seed": 2 * slots * len(context["instances"]) if context else None,
        "API_requests": 0, "actual_solves": 0, "Slurm_submitted": False}


def bind(path, protocol, output):
    cfg = load_config(path)
    cfg.update(source_u_protocol=str(Path(protocol).resolve()), source_u_protocol_sha256=sha(protocol))
    _training_snapshot(cfg)
    if Path(output).exists():
        raise ValueError("binding output must be new; do not overwrite a used config")
    write(output, cfg)
    return {"config": str(Path(output).resolve()), "source_u_protocol_sha256": cfg["source_u_protocol_sha256"],
            "actual_solves": 0, "API_requests": 0}


@contextmanager
def writer(directory):
    directory = Path(directory).resolve()
    if not directory.is_relative_to(ROOT / "runs/prototype-hh"):
        raise ValueError("use a new runs/prototype-hh/ directory, never an R15 run")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another prototype writer is active") from error
        yield directory


def prepare(path, seed, directory):
    cfg, context, binding, report = check(path)
    if report["pending"]:
        raise ValueError("PROTOCOL_PENDING: " + ", ".join(report["pending"]))
    if seed not in cfg["seeds"]:
        raise ValueError("seed outside declared three independent searches")
    if (directory / "Protocol.json").exists() or any(p.name != ".writer.lock" for p in directory.iterdir()):
        raise ValueError("prepare requires a fresh prototype directory")
    p = {"version": VERSION, "search": cfg["search"], "seed": seed, "binding": binding,
         "config_sha256": digest(cfg), "source_files": sources(), "engineering_only": False,
         "budget": report, **context}
    write(directory / "Protocol.json", p)
    identity = sha(directory / "Protocol.json")
    (directory / "Protocol.sha256").write_text(identity + "\n")
    s = {"identity": identity, "phase": "prepared", "cursor": 0, "iteration": 0,
         "records": [], "population": [], "children": [], "queue": [], "parents": [],
         "seen": {}, "inflight": None, "rng": random.Random(seed).getstate(), "search_wall_seconds": 0.0}
    write(directory / "checkpoint.json", s)
    return p, s


def load_run(directory):
    p, s = read(directory / "Protocol.json"), read(directory / "checkpoint.json")
    identity = sha(directory / "Protocol.json")
    if (p["version"] != VERSION or s["identity"] != identity
            or (directory / "Protocol.sha256").read_text().strip() != identity):
        raise ValueError("prototype run identity mismatch")
    verify_sources(p["source_files"])
    return p, s


def _plan(p, s, directory):
    rng = random.Random()
    rng.setstate(_tuple(s["rng"]))
    cfg, members = p["search"], len(p["members"])
    if s["cursor"] < cfg["population_size"]:
        s["queue"] = [genetics.initialize(rng, members, cfg)]
        s["parents"] = []
    else:
        pool = [{**s["records"][i], "candidate": read(directory / s["records"][i]["candidate_path"])}
                for i in s["population"]]
        s["queue"], s["parents"] = genetics.offspring(pool, rng, members, cfg)
    s["rng"] = rng.getstate()


def _commit(p, s, result, duplicate_of):
    pending = s["inflight"]
    record = {**{k: v for k, v in pending.items() if k != "candidate"},
              "valid": result["valid"], "J": -result["fitness"] if result["valid"] else None,
              "result_sha256": digest(result),
              "duplicate_of": duplicate_of, "evaluation_seconds": 0.0 if duplicate_of else result["evaluation_seconds"],
              "failure": result.get("failure")}
    index = s["cursor"]
    s["records"].append(record)
    s["seen"].setdefault(record["candidate_key"], index)
    s["cursor"] += 1
    s["queue"].pop(0)
    s["inflight"] = None
    n = p["search"]["population_size"]
    if index < n:
        s["population"].append(index)
    else:
        s["children"].append(index)
        if not s["queue"]:
            s["population"] = sorted(s["population"] + s["children"],
                                     key=lambda i: genetics.rank(s["records"][i]))[:n]
            s["children"] = []
            s["iteration"] += 1


def run_loop(p, s, directory, max_candidates=None, max_seconds=None, evaluator=None):
    evaluator = evaluator or evaluation.evaluate
    target = p["search"]["population_size"] + 2 * p["search"]["iterations"]
    started, cpu_started, count = time.monotonic(), time.process_time(), 0
    s["phase"] = "running"
    try:
        while s["cursor"] < target:
            if ((max_candidates is not None and count >= max_candidates)
                    or (max_seconds is not None and time.monotonic() - started >= max_seconds)
                    or (directory / "PAUSE").exists()):
                s["phase"] = "paused"
                break
            if s["inflight"] is not None:
                # Hard termination may leave an orphan worker. Even if a
                # result.json exists, a new process cannot certify its exit.
                raise RuntimeError("interrupted evaluation requires operator review; no automatic replay")
            if not s["queue"]:
                _plan(p, s, directory)
            candidate = s["queue"][0]
            key = model.validate(candidate, len(p["members"]))
            ident = f"P-{s['cursor']:07d}"
            prior_index = s["seen"].get(key)
            prior = s["records"][prior_index] if prior_index is not None else None
            result_path = prior["result_path"] if prior else f"worker-receipts/{ident}/result.json"
            candidate_path = f"candidates/{ident}.json"
            write(directory / candidate_path, candidate)
            s["inflight"] = {"id": ident, "candidate": candidate, "candidate_key": key,
                "stage": "initialization" if s["cursor"] < p["search"]["population_size"] else "evolution",
                "iteration": s["iteration"], "parents": list(s["parents"]),
                "candidate_path": candidate_path, "result_path": result_path}
            write(directory / "checkpoint.json", s)
            result = read(directory / result_path) if prior else evaluator(
                {"id": ident, "candidate": candidate}, {**p, "run_directory": str(directory)})
            if prior and digest(result) != prior["result_sha256"]:
                raise ValueError("cached evaluation changed")
            if result.get("mock") and not p["engineering_only"]:
                raise ValueError("mock result cannot enter a scientific search")
            evaluation.validate(result, p["instances"], p["config"]["problem"], p["config"].get("obp_actions"))
            _commit(p, s, result, prior["id"] if prior else None)
            count += 1
            write(directory / "checkpoint.json", s)
        if s["cursor"] == target:
            s["phase"] = "completed" if any(r["valid"] for r in s["records"]) else "completed_no_valid_candidate"
    except BaseException:
        s["phase"] = "blocked_evaluation" if s["inflight"] is not None else "paused"
        raise
    finally:
        s["search_wall_seconds"] += time.monotonic() - started
        s["controller_CPU_seconds"] = s.get("controller_CPU_seconds", 0.0) + time.process_time() - cpu_started
        write(directory / "checkpoint.json", s)
    return summary(p, s)


def summary(p, s):
    valid = [r for r in s["records"] if r["valid"]]
    best = min(valid, key=genetics.rank) if valid else None
    return {"version": VERSION, "problem": p["config"]["problem"], "seed": p["seed"],
        "phase": s["phase"], "logical_candidates": s["cursor"], "iteration": s["iteration"],
        "reserved_candidate_slots": s["cursor"] + int(s["inflight"] is not None),
        "unsettled_candidate_slots": int(s["inflight"] is not None),
        "initialization_candidates": sum(r["stage"] == "initialization" for r in s["records"]),
        "evolution_candidates": sum(r["stage"] == "evolution" for r in s["records"]),
        "valid_candidates": len(valid), "invalid_candidates": len(s["records"]) - len(valid),
        "cache_hits": sum(r["duplicate_of"] is not None for r in s["records"]),
        "unique_candidates": len(s["seen"]), "inflight": s["inflight"] is not None,
        "best_training_id": best["id"] if best else None, "best_training_J": best["J"] if best else None,
        "search_wall_seconds": s["search_wall_seconds"],
        "controller_CPU_seconds": s.get("controller_CPU_seconds", 0.0),
        "evaluation_wall_seconds": sum(r["evaluation_seconds"] for r in s["records"]),
        "API_requests": 0, "LLM_tokens": 0, "shared_H_construction_cost": p.get("shared_H_cost"),
        "engineering_only": p["engineering_only"], "holdout": "not_run"}


def export(directory):
    p, s = load_run(directory)
    output = directory / "exports"
    output.mkdir(exist_ok=True)
    report = summary(p, s)
    write(output / "summary.json", report)
    best_j = None
    with (output / "candidates.csv").open("w", newline="") as stream:
        fields = ["id", "stage", "iteration", "valid", "J", "best_training_J", "duplicate_of", "evaluation_seconds"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in s["records"]:
            if record["valid"]:
                best_j = record["J"] if best_j is None else min(best_j, record["J"])
            writer.writerow({**{k: record[k] for k in fields if k != "best_training_J"}, "best_training_J": best_j})
    unique = [r for r in s["records"] if r["duplicate_of"] is None]
    events = []
    for path in (directory / "worker-receipts").rglob("physical-solves.jsonl"):
        events.extend(json.loads(line) for line in path.read_text().splitlines() if line)
    rows = []
    with (output / "instance-results.csv").open("w", newline="") as stream:
        fields = ["candidate_id", "file", "raw_cost", "reference", "J", "captured_solves", "decisions_per_pass", "H_calls_per_pass", "worker_CPU_seconds", "complete_row_seconds"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in unique:
            result = read(directory / r["result_path"])
            if digest(result) != r["result_sha256"]:
                raise ValueError("saved evaluation changed")
            for row in result["instances"]:
                writer.writerow({"candidate_id": r["id"], "file": row["file"], "raw_cost": row["raw_cost"],
                    "reference": row["reference"], "J": row["score"], "captured_solves": row.get("captured_solves"),
                    "decisions_per_pass": len(row.get("member_sequence", [])), "H_calls_per_pass": sum(row.get("h_calls", [])),
                    "worker_CPU_seconds": row.get("worker_CPU_seconds"), "complete_row_seconds": row.get("complete_row_seconds")})
                rows.append(row)
    # Complete rows certify two passes. Physical events also retain partial
    # failed solves; a missing 'completed' event is not a known zero cost.
    costs = {"completed_logical_candidates": s["cursor"],
             "reserved_candidate_slots": s["cursor"] + int(s["inflight"] is not None),
             "unique_settled_evaluations": len(unique),
             "certified_solve_passes": sum(r.get("captured_solves", 0) for r in rows),
             "certified_decisions": sum(len(r.get("member_sequence", [])) * r.get("captured_solves", 0) for r in rows),
             "certified_H_calls": sum(sum(r.get("h_calls", [])) * r.get("captured_solves", 0) for r in rows),
             "physical_solve_starts": sum(e["event"] == "started" for e in events),
             "physical_solve_completions": sum(e["event"] == "completed" for e in events),
             "physical_solve_failures": sum(e["event"] == "failed" for e in events),
             "certified_rows_worker_CPU_seconds": sum(r.get("worker_CPU_seconds", 0) for r in rows),
             "failed_or_interrupted_CPU_seconds": None, "API_requests": 0, "LLM_tokens": 0}
    costs["controller_CPU_seconds"] = s.get("controller_CPU_seconds", 0.0)
    write(output / "costs.json", costs)
    if s["phase"] == "completed":
        best = min((r for r in s["records"] if r["valid"]), key=genetics.rank)
        frozen_candidate = read(directory / best["candidate_path"])
        if model.validate(frozen_candidate, len(p["members"])) != best["candidate_key"]:
            raise ValueError("champion candidate changed")
        artifact = {"kind": "frozen-prototype-router-v1", "engineering_only": p["engineering_only"],
            "binding": p["binding"], "seed": p["seed"], "search": p["search"],
            "source_search_protocol_sha256": s["identity"], "source_files": p["source_files"],
            "training_champion": {k: best[k] for k in ("id", "J", "candidate_key")},
            "candidate": frozen_candidate, "members": p["members"], "config": p["config"],
            "holdout": "not_run"}
        write(output / "frozen-model.json", artifact)
    return {**report, "exports": str(output)}


def summarize_runs(directories):
    pairs = [load_run(Path(d).resolve()) for d in directories]
    if len(pairs) != 3 or sorted(p["seed"] for p, _ in pairs) != [501, 502, 503]:
        raise ValueError("exactly the three independent training seeds required")
    first = pairs[0][0]
    for p, s in pairs:
        if (p["binding"] != first["binding"] or p["search"] != first["search"]
                or p["engineering_only"] != first["engineering_only"] or s["phase"] != "completed"):
            raise ValueError("only completed searches sharing the frozen inputs and parameters may be summarized")
    rows = sorted((summary(p, s) for p, s in pairs), key=lambda r: r["seed"])
    values = [r["best_training_J"] for r in rows]
    return {"scope": "training champions only; holdout results are separate", "runs": rows,
            "mean_training_J": statistics.mean(values), "sample_std_training_J": statistics.stdev(values),
            "limitation": "three searches share H; no H-reconstruction variation or significance claim"}


def summarize_evaluations(directories):
    values = [read(Path(d) / "Frozen-evaluation.json") for d in directories]
    if len(values) != 3 or sorted(r["seed"] for r in values) != [501, 502, 503]:
        raise ValueError("exactly three independently trained champions required")
    first = values[0]
    for row in values:
        if any(row[k] != first[k] for k in ("split", "manifest_sha256", "references_sha256", "binding", "search")):
            raise ValueError("frozen evaluations do not share the same declared inputs and protocol")
    rows = sorted(({"seed": r["seed"], "valid": r["valid"], "J": r["J"],
                    "model_sha256": r["frozen_model_sha256"]} for r in values), key=lambda r: r["seed"])
    complete = all(r["valid"] for r in rows)
    return {"scope": "frozen champions on " + first["split"], "runs": rows,
            "complete": complete, "mean_J": statistics.mean(r["J"] for r in rows) if complete else None,
            "sample_std_J": statistics.stdev(r["J"] for r in rows) if complete else None,
            "limitation": "shared H, three search seeds; never select a champion by these scores"}


def evaluate_frozen(artifact_path, manifest_path, reference_path, split, directory):
    artifact = read(artifact_path)
    if artifact["kind"] != "frozen-prototype-router-v1" or artifact["engineering_only"]:
        raise ValueError("a completed scientific training champion is required")
    verify_sources(artifact["source_files"])
    hs = artifact["members"]
    binding = artifact["binding"]
    if (binding["H_keys"] != [h["key"] for h in hs] or binding["state_spec_sha256"] != state.SPEC_SHA256
            or binding["problem"] != artifact["config"]["problem"]):
        raise ValueError("frozen H/state identity changed")
    if model.validate(artifact["candidate"], len(hs)) != artifact["training_champion"]["candidate_key"]:
        raise ValueError("frozen candidate differs from training champion")
    manifest = read(manifest_path)
    if split not in ("validation", "test") or manifest["split"] != split:
        raise ValueError("explicit validation/test manifest required; never reselect a champion")
    c = {**artifact["config"], "h_file": None, "holdout_split": split,
         "data_manifest": str(Path(manifest_path).resolve()),
         "reference_file": str(Path(reference_path).resolve()) if reference_path else None,
         "instance_count": len(manifest["instances"])}
    if c["problem"] == "obp":
        c["state_delivery"] = {**c["state_delivery"], "file": str(ROOT / "experiments/triad/obp_state_preset.py")}
    if c["problem"] == "tsp":
        ref = read(c["reference_file"]) if c["reference_file"] else {}
        d06 = read(ROOT / "experiments/triad/lkh.pending.json")
        if (ref.get("lkh_identity", {}).get("version") != d06["version"]
                or ref.get("parameters") != {k: d06[k] for k in ("runs", "max_trials", "seed", "integer_scale")}):
            raise ValueError("holdout needs its own fixed D06 LKH references; no LKH is run here")
    data, refs, _ = problems.load_inputs(c, allowed_splits=(split,))
    if set(r["sha256"] for r in data).intersection(binding["training_instance_contents"]):
        raise ValueError("training instances cannot be relabelled or mixed into independent evaluation")
    if any(p.name != ".writer.lock" for p in directory.iterdir()):
        raise ValueError("frozen evaluation requires a fresh directory")
    plan = {"frozen_model_sha256": sha(artifact_path), "split": split, "seed": artifact["seed"],
            "binding": binding, "search": artifact["search"],
            "manifest_sha256": sha(manifest_path), "references_sha256": digest(refs),
            "candidate_selection": "already frozen by training J; no reselection"}
    write(directory / "Evaluation-plan.json", plan)
    result = evaluation.evaluate({"id": "FROZEN", "candidate": artifact["candidate"]},
        {"config": c, "members": hs, "instances": data, "references": refs,
         "source_files": sources(), "run_directory": str(directory)})
    evaluation.validate(result, data, c["problem"], c.get("obp_actions"), holdout_split=split)
    write(directory / "Frozen-evaluation.json", {**plan, "valid": result["valid"],
        "J": -result["fitness"] if result["valid"] else None, "result": result})
    return {"split": split, "valid": result["valid"], "J": -result["fitness"] if result["valid"] else None,
            "champion_reselected": False, "API_requests": 0}
