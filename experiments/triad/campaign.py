#!/usr/bin/env python3
"""Start a new opt-in campaign and chain clean segments using Slurm dependencies."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "code"), str(ROOT)]
from heuristic_design.core.storage import read, sha, write
from experiments.triad import candidate_policy, configuration, parallel, shared_admission, six_ops, time_continuation
from experiments.triad.concurrency_probe import claim

PYTHON = "/public2/home/qiuqian/hdl-envs/portable-v2/bin/python"
R13 = Path("/public2/home/qiuqian/hdl-deploy/triad-tsp-lkh-candidate-20261117-r13")
MAX_SEGMENTS = 12


def view(batch, groups, policy):
    members = [(g, s) for g, s in six_ops.PAIRS[batch] if not groups or g in groups]
    if not members or groups and {g for g, _ in members} != set(groups):
        raise ValueError("groups must belong to the selected batch")
    rows = []
    for group, seed in members:
        config = six_ops.config(group)
        candidate_policy.validate(policy, config["evolution_request_cap"])
        pending = six_ops.check_assets(config)
        if group == "fjsp-u":
            pending.append("same-algorithm frozen FJSP U adapter")
        if policy["adoption"] != "adopted" or not policy["research_record"]:
            pending.append("research adoption of candidate policy")
        rows.append({"group": group, "seed": seed, "pending": pending,
                     "request_cap": config["initialization_request_cap"] + policy["evolution_attempt_cap"],
                     "config": str(six_ops.config_path(group))})
    return {"batch": batch, "members": rows, "policy": policy,
            "original_aggregate_cap": sum(r["request_cap"] for r in rows),
            "global_API_width": 1, "API_requests": 0, "actual_solves": 0, "submitted": False}


def start(args):
    policy = read(args.policy)
    preview = view(args.batch, args.group, policy)
    if not args.submit:
        return preview
    candidate_policy.validate(policy, 1000, real=True)
    if not (args.allow_api and args.allow_solves and args.confirm_exclusive_account
            and args.approve_requests == preview["original_aggregate_cap"]
            and args.max_segments is not None and 1 <= args.max_segments <= MAX_SEGMENTS
            and args.window_hours is not None and 1 <= args.window_hours <= 144
            and args.exclusive_hours is not None and max(48, args.window_hours + 1) <= args.exclusive_hours <= 168
            and args.wall_seconds is not None and 600 <= args.wall_seconds <= 604800):
        raise PermissionError("approve the full original reservation cap, campaign window, per-job walltime and segment count")
    if any(r["pending"] for r in preview["members"]):
        raise PermissionError("unresolved protocol or assets; run preview")
    if not (R13 / "release.json").is_file():
        raise PermissionError("prior R13 registry is unavailable")
    previous = R13 / "plans" / ("six-" + args.batch) / "Shared.json"
    if previous.exists():
        registered = {(r["group"], r["seed"]) for r in read(previous)["members"]}
        if registered.intersection((r["group"], r["seed"]) for r in preview["members"]):
            raise PermissionError("an original R13 experiment already has this identity")
    folder = ROOT / "plans" / ("candidate-" + args.batch)
    spec = folder.with_suffix(".spec.json")
    if folder.exists() or spec.exists():
        raise PermissionError("campaign identity already exists; inspect it")
    config = six_ops.config(preview["members"][0]["group"])
    account_gate = Path(config["account_gate"])
    if (account_gate / "generation.lock").exists():
        raise PermissionError("original shared account is occupied")
    claim(spec, {"batch_id": folder.name, "mode": "real", "members": preview["members"],
                 "runtime_policy": shared_admission.EXPLORE, "candidate_policy": policy,
                 "account_gate": str(account_gate), "min_request_interval_seconds": 1,
                 "queue_wait_seconds": 600, "window_seconds": args.window_hours * 3600,
                 "segment_seconds": args.wall_seconds})
    result = parallel.plan(spec, folder, args.exclusive_hours, True)
    path = Path(result["manifest"])
    claim(folder / "Campaign_authorization.json", {
        "manifest_sha256": sha(path), "approve_requests": args.approve_requests,
        "max_segments": args.max_segments, "release_account": args.release_account_on_completion,
        "expires_at": read(path)["account_exclusion"]["valid_until"], "allow_api": True, "allow_solves": True,
    })
    shared_admission.activate(path)
    launched = parallel.submit(path, "run", True, args.approve_requests, True, True)
    continuation = queue_followup(path, 1, launched)
    return {"initial": launched, "continuation": continuation}


def queue_followup(path, segment, receipt):
    """Persist one command claim before submitting one dependent controller."""
    ids = [r["job_id"] for r in receipt["receipts"]]
    if not ids or any(not j.isdigit() for j in ids) or len(ids) != len(set(ids)):
        raise PermissionError("exact worker job IDs required")
    m = shared_admission.load(path)
    c = configuration.load(m["members"][0]["config"], engineering=m["mode"]=="mock")
    r = c["resources"]
    cmd = ["sbatch", "--parsable", "--no-requeue", "--nodes=1", "--ntasks=1",
           "--cpus-per-task=1", "--mem=1024M", "--time=00:05:00",
           "--dependency=afterany:" + ":".join(ids), "--partition=" + r["partition"],
           "--chdir=" + str(ROOT), "--job-name=" + path.parent.name + "-review",
           "--output=" + str(ROOT / "logs" / (path.parent.name + "-review-%j.out")),
           "--error=" + str(ROOT / "logs" / (path.parent.name + "-review-%j.err"))]
    cmd.extend("--" + k + "=" + r[k] for k in ("account", "qos") if r[k])
    cmd.extend(["--wrap", shlex.join([PYTHON, "-s", "-B", str(Path(__file__).resolve()),
                                    "advance", "--manifest", str(path), "--segment", str(segment)])])
    record = path.parent / "campaign-control" / f"review-{segment:02d}.json"
    payload = {"state": "submission_reserved", "workers": ids, "manifest_sha256": sha(path),
               "command": cmd, "segment": segment}
    claim(record, payload)
    p = subprocess.run(cmd, check=True, text=True, capture_output=True, timeout=30)
    job = p.stdout.strip().split(";")[0]
    if not job.isdigit():
        raise RuntimeError("unknown controller submission; reservation retained")
    payload.update(state="submitted", job_id=job)
    shared_admission.durable(record, payload)
    return payload


def account_when_visible(m, workers):
    until = time.monotonic() + 45
    while True:
        try:
            accounting = time_continuation.accounting_for(m)
            if not all(accounting.get(j, {}).get("state") in time_continuation.TERMINAL for j in workers):
                raise time_continuation.AccountingPending("workers are not yet terminal in accounting")
            return accounting
        except time_continuation.AccountingPending:
            if time.monotonic() >= until:
                raise
            time.sleep(3)


def finish(path, assessment, segment, reason):
    exports = {}
    for row in shared_admission.load(path)["members"]:
        folder = Path(row["run_dir"]) / "exports"
        summary = folder / "summary.json"
        exports[row["run_id"]] = {"directory": str(folder), "summary_available": summary.is_file(),
                                 "summary_sha256": sha(summary) if summary.is_file() else None}
    result = {"segments": segment, "reason": reason, "assessment": assessment,
              "exports": exports, "submitted": False}
    write(path.parent / "Campaign_result.json", result)
    return result


def advance(path, segment):
    path = path.resolve()
    if not path.is_relative_to(ROOT / "plans") or not path.parent.name.startswith("candidate-"):
        raise PermissionError("only new candidate campaign plans can advance")
    m = shared_admission.load(path)
    auth = read(path.parent / "Campaign_authorization.json")
    control = path.parent / "campaign-control"
    record = read(control / f"review-{segment:02d}.json")
    if not (m.get("candidate_policy") and record["state"] == "submitted"
            and record["job_id"] == os.environ.get("SLURM_JOB_ID")
            and record["manifest_sha256"] == auth["manifest_sha256"] == sha(path)
            and record["segment"] == segment and 1 <= segment <= auth["max_segments"] <= MAX_SEGMENTS
            and auth["allow_api"] and auth["allow_solves"] and auth["approve_requests"] == m["total_request_cap"]):
        raise PermissionError("unmatched Slurm controller receipt or original campaign authorization")
    decision = control / f"decision-{segment:02d}.json"
    claim(decision, {"job_id": record["job_id"], "action": "inspection_reserved", "at": time.time()})
    try:
        accounting = account_when_visible(m, record["workers"])
        assessment = time_continuation.inspect(path, accounting=accounting)
        if assessment["blockers"] or not assessment["eligible"] or segment >= auth["max_segments"] or time.time() >= auth["expires_at"]:
            reason = ("scientific_complete" if assessment["scientific_complete"] and not assessment["blockers"]
                      else "campaign_finished_without_1000_or_requires_review")
            result = finish(path, assessment, segment, reason)
            if (auth["release_account"] and reason == "scientific_complete"
                    and all(r["summary_available"] for r in result["exports"].values())):
                result["account_release"] = six_ops.invoke("parallel.py", ["close", "--manifest", path])
                write(path.parent / "Campaign_result.json", result)
            return result
        chosen = assessment["selected"]
        # A clean time pause can select either member, including the remaining
        # seed after its paired worker stops at a documented local limit.
        receipt = parallel.submit(path, "resume", True, auth["approve_requests"], True, True,
                                  member=None if len(chosen) == len(m["members"]) else chosen[0])
        write(control / f"workers-{segment + 1:02d}.json", receipt)
        return {"submitted": True, "next": queue_followup(path, segment + 1, receipt)}
    except Exception as exc:
        write(control / f"error-{segment:02d}.json", {"type": type(exc).__name__, "error": str(exc)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("preview", "start"):
        command = sub.add_parser(name)
        command.add_argument("--policy", type=Path, required=True)
        command.add_argument("--batch", choices=six_ops.PAIRS, required=True)
        command.add_argument("--group", choices=configuration.GROUPS, action="append")
        if name == "start":
            for flag in ("submit", "allow-api", "allow-solves", "confirm-exclusive-account",
                         "release-account-on-completion"):
                command.add_argument("--" + flag, action="store_true")
            for flag in ("approve-requests", "exclusive-hours", "window-hours", "wall-seconds", "max-segments"):
                command.add_argument("--" + flag, required=True, type=int)
    status = sub.add_parser("status")
    status.add_argument("--manifest", type=Path, required=True)
    continuation = sub.add_parser("advance", help=argparse.SUPPRESS)
    continuation.add_argument("--manifest", type=Path, required=True)
    continuation.add_argument("--segment", type=int, required=True)
    args = parser.parse_args()
    if args.action == "preview":
        output = view(args.batch, args.group, read(args.policy))
    elif args.action == "start":
        output = start(args)
    elif args.action == "status":
        output = parallel.inspect(args.manifest)
    else:
        output = advance(args.manifest, args.segment)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
