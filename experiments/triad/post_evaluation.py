"""Frozen-champion evaluation using the R15 evaluator and independent Slurm jobs."""

import argparse
from dataclasses import asdict
import csv
import io
import json
import math
import os
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "code"), str(ROOT)]
from experiments.triad import evaluation, problems, shared_admission, time_continuation
from experiments.triad.concurrency_probe import claim
from heuristic_design.core.storage import digest, read, sha, write

SPLITS = ("validation", "test", "prospective-confirmation")
PLAN = "Frozen_evaluation_plan.json"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def specification(value, root):
    if value == "not_run":
        return None
    require(isinstance(value, dict) and set(value) == {"mode", "split", "manifest", "reference"},
            "research.holdout requires mode, split, manifest and reference")
    require(value["mode"] in ("auto", "manual") and value["split"] in SPLITS, "invalid holdout mode or split")
    require(isinstance(value["manifest"], str) and value["manifest"].strip(), "holdout manifest path required")
    reference = value["reference"]
    require(reference is None or isinstance(reference, str) and reference.strip(), "invalid holdout reference path")
    return {**value, "manifest": str((root / value["manifest"]).resolve()),
            "reference": str((root / reference).resolve()) if reference else None}


def content(problem, row):
    value = row["value"]
    if problem == "tsp":
        return digest([[float(coord) for coord in point] for point in value["coordinates"]])
    if problem == "obp":
        return digest([float(value["capacity"]), [float(item) for item in value["items"]]])
    return row["sha256"]


def inputs(spec, config, training):
    manifest = Path(spec["manifest"])
    reference = Path(spec["reference"]) if spec["reference"] else None
    problem, split = config["problem"], spec["split"]
    info = read(manifest)
    if problem == "fjsp" and isinstance(info.get("split"), dict):
        registered = read(ROOT / "data/fjsp_manifest.json")
        require(split in ("validation", "test") and info["split"] == registered["split"]
                and info["files"] == registered["files"], "FJSP split registry differs from the frozen Behnke inventory")
        info = {"problem": problem, "split": split, "instances": [
            {"file": name, "path": "fjsp/" + name, "sha256": registered["files"][name]["sha256"]}
            for name in registered["split"][split]]}
    require(info["split"] == split and info["problem"] == problem, "holdout manifest problem/split differs")
    require(isinstance(info["instances"], list) and info["instances"], "empty holdout manifest")
    c = {**config, "h_file": None, "data_manifest": str(manifest),
         "reference_file": str(reference) if reference else None,
         "instance_count": len(info["instances"]), "holdout_split": split, "evaluation_concurrency": 1}
    if problem == "tsp" and config["mode"] == "real":
        trained, held = read(config["reference_file"]), read(reference)
        fields = ("lkh_identity", "parameters", "distance_protocol")
        require(all(held[name] == trained[name] for name in fields)
                and isinstance(held.get("execution_receipt_sha256"), str)
                and len(held["execution_receipt_sha256"]) == 64,
                "holdout D06 must match the training binary and parameters and carry its execution receipt hash")
    rows, refs, _ = problems.load_inputs(c, allowed_splits=(split,), manifest=info)
    held = {content(problem, row) for row in rows}
    require(len(held) == len(rows) and len({r["file"] for r in rows}) == len(rows),
            "duplicate holdout instances")
    require(not held.intersection(content(problem, row) for row in training),
            "holdout contains training instances")
    if reference and problem != "tsp":
        require(read(reference)["instances"] == refs, "provided references differ from the existing problem rule")
    if problem == "tsp" and config["mode"] == "real":
        for row, ref in zip(rows, refs):
            tour, n = ref["tour"], len(row["value"]["coordinates"])
            require(len(tour) == n + 1 and tour[0] == tour[-1] == 0
                    and set(tour[:-1]) == set(range(n)) and ref["reference"] > 0, "invalid D06 tour")
    identity = {"manifest_sha256": sha(manifest), "reference_file_sha256": sha(reference) if reference else None,
                "reference_rows_sha256": digest(refs), "instance_rows_sha256": digest(rows),
                "instances": len(rows), "solve_limit_per_initial_attempt": 2 * len(rows)}
    return c, rows, refs, identity


def preflight(spec, config, training_ready):
    if spec is None:
        return {"mode": "not_run", "pending": []}
    pending = []
    if not Path(spec["manifest"]).is_file():
        pending.append("holdout manifest missing: " + spec["manifest"])
    if config["problem"] == "tsp" and not spec["reference"]:
        pending.append("TSP holdout requires a separate D06 reference file")
    if spec["reference"] and not Path(spec["reference"]).is_file():
        pending.append("holdout reference missing: " + spec["reference"])
    if not training_ready:
        pending.append("training assets must be available to verify holdout independence")
    if pending:
        return {**spec, "pending": pending}
    try:
        training, _, _ = problems.load_inputs(config)
        _, _, _, binding = inputs(spec, config, training)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        return {**spec, "pending": [str(exc)]}
    return {**spec, "binding": binding, "pending": []}


def plan(manifest):
    authorization = manifest.parent / "Campaign_authorization.json"
    if not authorization.is_file():
        return None
    auth = read(authorization)
    if not auth.get("holdout_plan_sha256"):
        return None
    file = manifest.parent / PLAN
    require(sha(file) == auth["holdout_plan_sha256"], "frozen holdout plan changed")
    value = read(file)
    require(value["manifest_sha256"] == auth["manifest_sha256"] == sha(manifest), "holdout campaign differs")
    return value


def champion_identity(p, champion, run, frozen_path):
    config = p["config"]
    candidate = champion["candidate"]
    members = p["members"] if p["run_kind"] == "u" else [candidate]
    return {"protocol_sha256": sha(run / "Protocol.json"), "champion_sha256": sha(frozen_path),
            "candidate_key": candidate["key"], "candidate_code_sha256": sha(run / "exports/champion.py"),
            "champion_id": champion["id"], "training_J": champion["J"],
            "problem": config["problem"], "method": p["run_kind"], "seed": config["search_seed"],
            "ordered_H_keys": [h["key"] for h in members], "H_members_sha256": digest(members),
            "shared_H_file_sha256": p.get("source_cost", {}).get("H_file_sha256"),
            "training_instances_sha256": digest(p["instances"]),
            "training_references_sha256": digest(p["references"]),
            "training_sources_sha256": digest(p["source_files"])}


def training_export(run):
    """Read the existing selection. Never select a replacement."""
    cp = read(run / "checkpoint.json")
    p = read(run / "Protocol.json")
    summary = read(run / "exports/summary.json")
    config = p["config"]
    filename = "frozen_engineering_candidate.json" if config["mode"] == "mock" else "frozen_training_champion.json"
    frozen_path = run / "exports" / filename
    frozen = read(frozen_path)
    champion = frozen["champion"]
    require(cp["phase"] == summary["phase"] == "completed"
            and cp["successful_evolution_responses"] == config["evolution_request_cap"]
            and cp["identity"] == frozen["protocol_sha256"] == sha(run / "Protocol.json")
            and frozen["metrics"] == p["metrics"] and frozen["holdout"] == "not_run",
            "training or frozen export does not match the completed checkpoint")
    exported = read(run / "exports/champion.json")
    candidate = champion["candidate"]
    require(champion["valid"] and math.isfinite(champion["J"])
            and champion["id"] == exported["id"] == summary["champion_id"]
            and champion["J"] == exported["J"] == summary["best_J"]
            and candidate == exported["candidate"] and exported["protocol_sha256"] == cp["identity"]
            and (run / "exports/champion.py").read_bytes() == candidate["code"].encode(),
            "training J or the frozen candidate changed")
    members = p["members"] if p["run_kind"] == "u" else [candidate]
    identity = champion_identity(p, champion, run, frozen_path)
    saved = run / "exports/champion_identity.json"
    if saved.exists():
        require(read(saved) == identity, "champion identity receipt differs")
    return p, candidate, members, identity


def attempts(manifest, run_id):
    return sorted((manifest.parent / "holdout" / run_id).glob("attempt-*"))


def scheduler_states(ids):
    if not ids:
        return {}
    result = subprocess.run(["sacct", "-n", "-P", "-X", "-j", ",".join(ids),
                             "--format=JobIDRaw,State,ExitCode"], check=True, text=True, capture_output=True, timeout=15)
    return {job: state.split()[0] for job, state, _ in
            (line.rstrip("|").split("|") for line in result.stdout.splitlines()) if job in ids and state}


def queue(manifest, rows, *, retry=False):
    spec = plan(manifest)
    if spec is None:
        return []
    submitted = []
    for row in rows:
        run = Path(row["run_dir"])
        history = attempts(manifest, row["run_id"])
        try:
            if history:
                if not retry:
                    continue
                last = history[-1]
                if (last / "result.json").is_file() and read(last / "result.json")["complete"]:
                    continue
                previous = read(last / "submission.json")
                require(previous["state"] == "submitted" and scheduler_states([previous["job_id"]])
                        .get(previous["job_id"]) in time_continuation.TERMINAL,
                        "previous holdout job is active or its submission is unknown")
            p, _, _, identity = training_export(run)
            require(identity["seed"] == row["seed"] and row["group"] == identity["problem"] + "-" + identity["method"],
                    "training member identity differs")
            target = manifest.parent / "holdout" / row["run_id"]
            directory = target / f"attempt-{len(history) + 1:06d}"
            receipt = directory / "submission.json"
            resources = p["config"]["resources"]
            # A separate walltime based only on the confirmed held-out row count.
            wall_minutes = max(5, math.ceil((45 * spec["binding"]["instances"] + 120) / 60))
            cmd = ["sbatch", "--parsable", "--no-requeue", "--nodes=1", "--ntasks=1", "--cpus-per-task=2",
                   "--mem=" + str(resources["memory_mib"]) + "M", "--time=" + str(wall_minutes),
                   "--chdir=" + str(ROOT), "--job-name=" + row["run_id"] + "-holdout",
                   "--output=" + str(ROOT / "logs" / (row["run_id"] + "-holdout-%j.out")),
                   "--error=" + str(ROOT / "logs" / (row["run_id"] + "-holdout-%j.err")),
                   "--partition=" + resources["partition"]]
            cmd += ["--" + k + "=" + resources[k] for k in ("account", "qos") if resources[k]]
            cmd += ["--wrap", shlex.join([sys.executable, "-s", "-B", str(Path(__file__).resolve()),
                                        str(manifest), row["run_id"], str(directory)])]
            record = {"state": "submission_reserved", "identity": identity, "manifest_sha256": sha(manifest),
                      "plan_sha256": sha(manifest.parent / PLAN), "command": cmd}
            claim(receipt, record)
            result = subprocess.run(cmd, check=True, text=True, capture_output=True, timeout=30)
            job = result.stdout.strip().split(";")[0]
            require(job.isdigit(), "unknown holdout submission receipt")
            record.update(state="submitted", job_id=job)
            shared_admission.durable(receipt, record)
            submitted.append({"run_id": row["run_id"], "job_id": job, "state": "submitted"})
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
            submitted.append({"run_id": row["run_id"], "state": "not_submitted_or_unknown", "error": str(exc)})
    return submitted


def wait_submission(path, job):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            value = read(path)
        except (FileNotFoundError, json.JSONDecodeError):
            value = {}
        if value.get("state") == "submitted":
            require(value["job_id"] == job, "wrong holdout job identity")
            return value
        time.sleep(0.25)
    raise ValueError("holdout job receipt unavailable")


def results(manifest, run_id):
    paths = attempts(manifest, run_id)
    return [(d, read(d / "result.json")) for d in paths if (d / "result.json").is_file()]


def run_holdout(manifest, run_id, directory):
    m = shared_admission.load(manifest)
    row, = [row for row in m["members"] if row["run_id"] == run_id]
    history = attempts(manifest, run_id)
    require(m["members"] and directory in history and history[-1] == directory, "unregistered holdout attempt")
    receipt = wait_submission(directory / "submission.json", os.environ.get("SLURM_JOB_ID"))
    # One writer per attempt, including a repeated launch of the same local command.
    claim(directory / "worker.json", {"job_id": receipt["job_id"]})
    require(receipt["manifest_sha256"] == sha(manifest) and receipt["plan_sha256"] == sha(manifest.parent / PLAN),
            "worker holdout plan identity changed")
    spec = plan(manifest)
    p, candidate, members, identity = training_export(Path(row["run_dir"]))
    require(identity == receipt["identity"], "worker frozen champion changed")
    c, rows, refs, binding = inputs(spec, p["config"], p["instances"])
    require(binding == spec["binding"], "holdout inputs changed since launch")
    require(all(sha(ROOT / path) == checksum for path, checksum in p["source_files"].items()),
            "training-bound evaluator source changed")
    prior = results(manifest, run_id)
    prefix = []
    if prior:
        previous = prior[-1][1]
        require(previous["identity"] == identity and previous["binding"] == binding and not previous["complete"],
                "prior holdout result differs or is complete")
        prefix = previous["rows"]
        require(len(prefix) < len(rows), "invalid prior holdout prefix")
    if p["run_kind"] == "eoh":
        candidate = (None if c["problem"] == "obp" else asdict(problems.u_language.validate(
            "def use_heuristics(state):\n    return 0\n", "singleton H host", 1)))
    n = len(prefix)
    if m["mode"] == "mock":
        fresh = [{"file": r["file"], "score": 0.0, "reference": ref["reference"],
                  "raw_cost": ref["reference"], "captured_solves": 0} for r, ref in zip(rows[n:], refs[n:])]
        result = {"valid": True, "fitness": 0.0, "instances": fresh, "mock": True, "failure": None}
    else:
        result = evaluation.evaluate({"id": "FROZEN", "candidate": candidate},
            {**p, "config": c, "members": members, "instances": rows[n:], "references": refs[n:],
             "run_directory": str(directory)})
    complete_rows = prefix + result["instances"]
    require(all(row["reference"] == ref["reference"] for row, ref in zip(complete_rows, refs)),
            "evaluated reference differs from the holdout plan")
    score = sum(r["score"] for r in complete_rows) / len(rows) if result["valid"] else None
    combined = {"valid": result["valid"], "fitness": -score if score is not None else None,
                "instances": complete_rows, "mock": m["mode"] == "mock"}
    evaluation.validate(combined, rows, c["problem"], c.get("obp_actions"), holdout_split=spec["split"])
    value = {"identity": identity, "binding": binding, "split": spec["split"], "complete": result["valid"],
             "engineering_only": m["mode"] == "mock", "holdout_J": score, "rows": complete_rows,
             "failure": result["failure"], "wall_seconds": result.get("evaluation_seconds"), "API_requests": 0}
    write(directory / "result.json", value)
    if value["complete"]:
        publish(manifest, m)
    return value


def overview(manifest, rows, members):
    try:
        spec, error = plan(manifest), None
    except (OSError, ValueError, KeyError) as exc:
        spec, error = None, str(exc)
    mode = "blocked" if error else spec["mode"] if spec else "not_run"
    for row, item in zip(rows, members):
        item["training_complete"] = item["phase"] == "completed" and item["successful_evolution"] == item["target"]
        item["champion_frozen"] = False
        if item["training_complete"]:
            try:
                _, _, _, item["champion"] = training_export(Path(row["run_dir"]))
                item["champion_frozen"] = True
            except (OSError, ValueError, KeyError) as exc:
                item["champion_error"] = str(exc)
        history = attempts(manifest, row["run_id"]) if spec else []
        out = {"phase": mode if not spec else "waiting_for_training", "complete": False,
               "J": None, "split": spec["split"] if spec else None}
        if spec and item["training_complete"]:
            out["phase"] = "ready" if item["champion_frozen"] else "blocked"
        if history:
            last = history[-1]
            try:
                receipt = read(last / "submission.json")
            except (FileNotFoundError, json.JSONDecodeError):
                receipt = {"state": "submission_reserved"}
            out.update(phase=receipt["state"], job=receipt.get("job_id"), attempts=len(history))
            if (last / "result.json").is_file():
                result = read(last / "result.json")
                matches = (result["identity"] == item.get("champion") and result["binding"] == spec["binding"]
                           and result["split"] == spec["split"])
                complete = (matches and result["complete"] and len(result["rows"]) == spec["binding"]["instances"]
                            and result["holdout_J"] is not None and math.isfinite(result["holdout_J"]))
                out.update(phase="completed" if complete else "failed", complete=complete,
                           J=result["holdout_J"] if complete else None, evaluated_rows=len(result["rows"]),
                           failure=result["failure"] if matches else "holdout result identity differs")
            elif receipt["state"] == "submitted":
                try:
                    state = scheduler_states([receipt["job_id"]]).get(receipt["job_id"])
                    if state:
                        out["slurm_state"] = state
                        out["phase"] = "interrupted" if state in time_continuation.TERMINAL else state.lower()
                except (OSError, subprocess.SubprocessError, ValueError):
                    pass
        item["holdout"] = out
        item["experiment_complete"] = item["champion_frozen"] and out["complete"]
    complete = bool(spec) and all(r["experiment_complete"] for r in members)
    return {"mode": mode, "error": error, "training_complete": all(r["training_complete"] for r in members),
            "champions_frozen": all(r["champion_frozen"] for r in members),
            "holdout_complete": bool(spec) and all(r["holdout"]["complete"] for r in members),
            "experiment_complete": complete,
            "summary_file": str(manifest.parent / "holdout/method-summary.csv")
            if complete and (manifest.parent / "holdout/method-summary.csv").is_file() else None}


def tables(manifest, members, archive=None):
    seeds, instances, statistics_rows = [], [], []
    for item in members:
        run_id = item["run_id"]
        saved = results(manifest, run_id)
        _, last = saved[-1] if saved else (None, {})
        cost = {"started": 0, "completed": 0, "failed": 0}
        history = attempts(manifest, run_id)
        for directory in history:
            events = directory / "worker-receipts/FROZEN/physical-solves.jsonl"
            if events.is_file():
                events_raw = events.read_bytes()
                for line in events_raw.splitlines():
                    try:
                        event = json.loads(line)["event"]
                    except (ValueError, KeyError):
                        continue  # interrupted line is retained in the archived evidence
                    if event in cost:
                        cost[event] += 1
                if archive:
                    archive.writestr(f"{run_id}/holdout/{directory.name}/physical-solves.jsonl", events_raw)
            for filename in ("submission.json", "result.json"):
                if archive and (directory / filename).is_file():
                    archive.write(directory / filename, f"{run_id}/holdout/{directory.name}/{filename}")
        train = read(item["summary_file"]) if item["summary_file"] else {}
        best = train.get("best_J") if item["training_complete"] else None
        held = last.get("holdout_J") if item["experiment_complete"] else None
        seed = {"group": item["group"], "seed": item["seed"]}
        elapsed = [x["wall_seconds"] for _, x in saved if x["wall_seconds"] is not None]
        seeds.append({**seed, "engineering_only": train.get("engineering_only"),
                      "champion_frozen": item["champion_frozen"], "training_J": best,
                      "holdout_split": item["holdout"]["split"], "holdout_phase": item["holdout"]["phase"],
                      "holdout_J": held, "holdout_minus_training_J": held - best if held is not None else None,
                      "training_api_sends": train.get("confirmed_sends"), "training_known_tokens": train.get("known_tokens"),
                      "training_unknown_usage": train.get("unknown_usage_attempts"),
                      "training_physical_passes": train.get("physical_passes"), "holdout_api_sends": 0,
                      "holdout_solve_starts": cost["started"], "holdout_solve_completions": cost["completed"],
                      "holdout_solve_failures": cost["failed"],
                      "holdout_recorded_wall_seconds": sum(elapsed) if elapsed else None,
                      "holdout_attempts_without_wall_receipt": len(history) - len(elapsed),
                      "holdout_certified_worker_CPU_seconds": sum(r.get("worker_CPU_seconds", 0) for r in last.get("rows", []))})
        for r in last.get("rows", []):
            instances.append({**seed, "split": last["split"], "file": r["file"], "J": r["score"],
                              "raw_cost": r["raw_cost"], "reference": r["reference"],
                              "physical_solves_certified": r["captured_solves"],
                              "worker_CPU_seconds": r.get("worker_CPU_seconds"), "row_seconds": r.get("complete_row_seconds")})
    for group in sorted({r["group"] for r in seeds}):
        expected = [r for r in seeds if r["group"] == group]
        line = {"group": group, "seeds_planned": len(expected)}
        for label, field in (("training", "training_J"), ("holdout", "holdout_J"), ("paired_difference", "holdout_minus_training_J")):
            values = [r[field] for r in expected if r[field] is not None]
            complete = len(values) == len(expected)
            line.update({label + "_complete_seeds": len(values),
                         label + "_mean_J": statistics.mean(values) if complete else None,
                         label + "_sample_sd_J": statistics.stdev(values) if complete and len(values) > 1 else None})
        statistics_rows.append(line)
    return {"seed-results.csv": seeds, "method-summary.csv": statistics_rows, "holdout-per-instance.csv": instances}


def csv_text(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def export(archive, manifest, members):
    try:
        spec = plan(manifest)
    except (OSError, ValueError, KeyError):
        spec = None
    if spec:
        archive.writestr(PLAN, json.dumps(spec, indent=2, ensure_ascii=False))
    for name, rows in tables(manifest, members, archive).items():
        if rows:
            archive.writestr(name, csv_text(rows))


def publish(manifest, m):
    members = []
    for row in m["members"]:
        history = attempts(manifest, row["run_id"])
        if not history or not (history[-1] / "result.json").is_file() or not read(history[-1] / "result.json")["complete"]:
            return
        run = Path(row["run_dir"])
        summary = run / "exports/summary.json"
        s = read(summary)
        members.append({"phase": s["phase"], "successful_evolution": s["successful_evolution_responses"],
                        "target": s["successful_evolution_target"], "summary_file": str(summary),
                        "group": row["group"], "seed": row["seed"], "run_id": row["run_id"]})
    if not overview(manifest, m["members"], members)["experiment_complete"]:
        return
    directory = manifest.parent / "holdout"
    for name, rows in tables(manifest, members).items():
        if rows:
            # Concurrent finishers can publish the same immutable finished snapshot.
            with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as f:
                f.write(csv_text(rows))
            Path(f.name).replace(directory / name)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("manifest", type=Path)
    cli.add_argument("run_id")
    cli.add_argument("attempt_dir", type=Path)
    args = cli.parse_args()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    result = run_holdout(args.manifest, args.run_id, args.attempt_dir)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
    sys.exit(0 if result["complete"] else 2)
