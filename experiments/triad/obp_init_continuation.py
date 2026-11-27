#!/usr/bin/env python3
"""One-time OBP-EoH continuation of the three closed, settled I1 batches."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "code"), str(ROOT)]

from experiments.triad import campaign, candidate_policy, runtime, shared_admission as shared, time_continuation
from experiments.triad.concurrency_probe import claim
from fjsp_usage.research_real.real_transport import OBSERVATION_VERSION, WIRE_VERSION
from heuristic_design.core import execution
from heuristic_design.core.storage import digest, read, sha, write
from tools import experiment

OLD = "triad-candidate-runtime-20261122-r15-obp-parallel"
OLD_COMMIT = "a1e91ef5f1089db94a87accbff8c0fc762853d6f"
NEW = "triad-candidate-runtime-20261122-r15-obp-native"
SOURCE_PLAN = "candidate-lab-r15-obp-eoh-long"
CONFIG = ROOT / "configurations/experiments/r15-obp-eoh-long.json"
SEEDS = {501: "639696", 502: "639697", 503: "639698"}
REVIEW = "639699"
STOP = "native initialization ended with fewer than N finite distinct parents; no refill"
CHANGED_SOURCES = {"experiments/triad/candidate_policy.py", "experiments/triad/runtime.py",
                   "experiments/triad/campaign.py", "tools/experiment.py"}
PAST_OUTPUTS = ("worker-receipts", "prompts", "responses", "wire_responses", "populations", "Events.jsonl")


def require(condition, error):
    if not condition:
        raise ValueError(error)


def normalized(config):
    config = deepcopy(config)
    for key in ("initialization_policy", "account_gate", "shared_manifest", "data_manifest"):
        config.pop(key, None)
    config["state_delivery"].pop("file")
    return config


def check_snapshot(protocol, state, snapshot):
    # P000_initial precedes the first E1 parent draw. The strict gate runs
    # after that draw, with no reservation. Replay the draw only as a check.
    candidate = deepcopy(state)
    candidate["eoh"] = deepcopy(snapshot)
    require(snapshot["stage"] == "evolution" and snapshot["operator_cursor"] == 0,
            "initial population snapshot is not at the first evolution slot")
    config = {**protocol["config"], "initialization_policy": "native_EoH"}
    with TemporaryDirectory() as scratch:
        task, parents = runtime.Adapter().task_context(Path(scratch), candidate, {**protocol, "config": config},
                                                       {"id": "offline-parent-draw"}, state["cursor"])
    require(task["operator"] == "E1" and len(parents) == 2 and candidate["eoh"] == state["eoh"],
            "the saved RNG difference is not the unsubmitted first E1 draw")


def audit_source(parent):
    path = parent / "plans" / SOURCE_PLAN / "Shared.json"
    manifest = shared.load(path)
    result = read(path.parent / "Campaign_result.json")
    closure = read(path.parent / "Closed.json")
    require(read(parent / "release.json")["engineering_commit"] == OLD_COMMIT
            and manifest["mode"] == "real" and shared.independent(manifest),
            "wrong source release or batch identity")
    require(result["reason"] == "ended_incomplete" and result["segments"] == 1
            and result["account_release"] == {"closed": True, "resume_prohibited": True}
            and closure["manifest_sha256"] == sha(path), "parent is not durably closed")
    require(not (Path(manifest["account_gate"]) / "generation.lock").exists()
            and not (path.parent / "gate/STOP.json").exists(), "parent batch lock or STOP retained")
    accounting = time_continuation.accounting_for(manifest)
    require(set(accounting) == set(SEEDS.values())
            and all(r["state"] in time_continuation.TERMINAL for r in accounting.values()),
            "missing or active source Slurm job")
    review = subprocess.run(["sacct", "-n", "-P", "-X", "-j", REVIEW, "--format=JobIDRaw,State,ExitCode"],
                            check=True, text=True, capture_output=True, timeout=30)
    require(review.stdout.strip() == REVIEW + "|COMPLETED|0:0", "source review is not terminal")

    audited = {}
    for member in manifest["members"]:
        seed = member["seed"]
        old = Path(member["run_dir"])
        cfg = read(Path(member["config"]))
        require(seed in SEEDS and member["group"] == "obp-eoh"
                and old.is_relative_to(parent / "runs" / SOURCE_PLAN)
                and read(old / "latest-submission.json")["job_id"] == SEEDS[seed], "source seed or job mismatch")
        require(not any((old / label).exists() for label in
                        (".execution.lock", ".coordinator.lock", "Stop.json", "Clock_quarantine.json"))
                and not (Path(cfg["account_gate"]) / "generation.lock").exists(), f"seed {seed} still has a writer")
        p, s = runtime.protocol_state(old)
        require(s["phase"] == "initialization_incomplete" and s["pause_reason"] == STOP
                and s["cursor"] == s["eoh"]["initialization_requests"] == 10
                and s.get("successful_evolution_responses", 0) == s["eoh"]["operator_cursor"] == 0
                and len(s["population"]) == 1 and len(s["eoh"]["population"]) == 10
                and all(t["operator"] == "I1" and t["status"] == "completed" and t["valid"]
                        and t["evaluation_key"] in s["evaluations"]
                        for t in s["tasks"].values()), f"seed {seed} is not the diagnosed I1 state")
        require(p["run_kind"] == "eoh" and p["config"]["initialization_policy"] == "native_N_finite_or_fail"
                and p["config"]["search_seed"] == seed and p["config"]["instance_count"] == 96
                and sha(Path(member["config"])) == p["config_sha256"]
                and sha(old / "Tasks.json") == p["tasks_sha256"], "source protocol identity differs")
        for name, expected in p["source_files"].items():
            require(sha(parent / name) == expected, f"archived source changed: {name}")
            if name not in CHANGED_SOURCES:
                require(sha(ROOT / name) == expected, f"evaluation or search source changed: {name}")
        journal = read(old / "API_attempts.json")
        require(not journal["halt_reason"] and set(journal["requests"]) == set(s["tasks"])
                and len(journal["api_attempts"]) == 10
                and all(a["status"] == "completed" and a["send_confirmed"] and a.get("finished_at")
                        for a in journal["api_attempts"].values())
                and candidate_policy.costs(journal)["reservations_by_stage"] == {"initialization": 10},
                "source API journal includes an unsettled, failed or additional request")
        adapter = runtime.Adapter()
        adapter.p = p
        execution.ledger(old, s, p, adapter=adapter)
        time_continuation.check_calendar(cfg, read(old / "Run_clock.json"), time.time(), full_segment=False)
        snapshot = read(old / "populations/P000_initial.json")
        check_snapshot(p, s, snapshot)
        audited[seed] = (old, p, s, snapshot, journal)
    require(set(audited) == set(SEEDS), "all three diagnosed seeds are required")
    return audited


def verify_import(directory, protocol):
    receipt = protocol["obp_init_continuation"]
    require(protocol["config"]["group"] == "obp-eoh"
            and protocol["config"]["initialization_policy"] == "native_EoH",
            "continuation is only for adopted OBP-EoH native admission")
    for name, expected in receipt["evidence"].items():
        require(sha(directory / "parent-evidence" / name) == expected, f"inherited evidence changed: {name}")
    old = read(directory / "parent-evidence/API_attempts.json")
    current = read(directory / "API_attempts.json")
    for field in ("api_attempts", "requests"):
        require(all(current[field].get(k) == row for k, row in old[field].items()),
                "inherited requests changed or were refunded")


def identity_only(protocol, binding):
    config = candidate_policy.client_config(protocol)
    wire = digest({"provider": config.payload()["provider"], "mode": config.mode,
                   "transport_version": WIRE_VERSION, "observation_version": OBSERVATION_VERSION})
    candidate = digest({"wire": wire, "candidate_policy": protocol["config"]["candidate_policy"]})
    def deny(*args, **kwargs):
        raise RuntimeError("identity-only import cannot send")
    return SimpleNamespace(identity=digest({"transport": candidate, "batch": binding, "mode": "independent-v1"}),
                           preflight=deny, dispatch=deny)


def import_member(manifest, member, source):
    old, parent, state, snapshot, old_journal = source
    directory = Path(member["run_dir"])
    cap = member["request_cap"]
    protocol = runtime.prepare(directory, member["config"], allow_api=True, approve_budget=cap)
    require(normalized(protocol["config"]) == normalized(parent["config"])
            and all(protocol[key] == parent[key] for key in
                    ("instances", "references", "members", "budgets", "tasks_sha256",
                     "obp_execution_contract", "H_prompt_contract")), "protocol changed beyond native admission")
    evidence = directory / "parent-evidence"
    evidence.mkdir()
    for name in ("Protocol.json", "checkpoint.json", "API_attempts.json"):
        shutil.copyfile(old / name, evidence / name)
    shutil.copyfile(old / "Run_clock.json", directory / "Run_clock.json")
    for name in PAST_OUTPUTS:
        source_path = old / name
        if source_path.is_dir():
            shutil.copytree(source_path, directory / name)
        else:
            shutil.copyfile(source_path, directory / name)
    protocol["obp_init_continuation"] = {
        "parent_protocol_sha256": state["identity"], "parent_job_id": SEEDS[member["seed"]],
        "parent_run_id": parent["run_id"], "native_initialization_requests_inherited": 10,
        "evidence": {path.name: sha(path) for path in evidence.iterdir()},
    }
    write(directory / "Protocol.json", protocol)
    protocol_hash = sha(directory / "Protocol.json")
    (directory / "Protocol.sha256").write_text(protocol_hash + "\n")
    checkpoint = {**state, "identity": protocol_hash, "phase": "paused",
                  "pause_reason": "adopted native OBP-EoH initialization continuation",
                  "eoh": deepcopy(snapshot)}
    write(directory / "checkpoint.json", checkpoint)
    binding = shared.binding(manifest, directory, member["config"])
    journal = candidate_policy.journal(None, directory, checkpoint, protocol,
                                       read(directory / "Run_clock.json")["deadline"],
                                       identity_only=identity_only(protocol, binding))
    journal.data.update({field: old_journal[field] for field in ("api_attempts", "requests")})
    journal.save()
    shared.attach(directory, binding)
    adapter = shared.adapter(binding)
    adapter.check_run(directory)
    execution.ledger(directory, checkpoint, protocol, adapter=adapter)
    return {"seed": member["seed"], "run_directory": str(directory),
            "checkpoint_sha256": sha(directory / "checkpoint.json"), "inherited_initialization": 10}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "submit"))
    parser.add_argument("--approve-evolution-reservations", type=int)
    args = parser.parse_args()
    require(ROOT.name == NEW, "use the designated new independent deployment directory")
    parent = ROOT.parent / OLD
    source = audit_source(parent)
    doc, folder = experiment.load_document(CONFIG)
    members, preview = experiment.prepare(doc, inherited_window=doc["execution"]["window_hours"] * 3600)
    require(preview["ready_for_submission_checks"], "native admission config is not ready")
    evolution_cap = sum(c["candidate_policy"]["evolution_attempt_cap"] for c, _ in members)
    response = {"inherited_initialization": 30, "new_initialization": 0, "successful_evolution_target_per_seed": 1000,
                "remaining_evolution_reservation_cap": evolution_cap, "submitted": False}
    manifest = folder / "Shared.json"
    receipt = folder / "OBP-import-complete.json"
    if args.action == "check":
        require(args.approve_evolution_reservations is None, "check does not accept execution approval")
    elif args.action == "prepare":
        require(args.approve_evolution_reservations is None, "prepare does not accept execution approval")
        path = experiment.create_plan(doc, folder, members, preview)
        rows = [import_member(path, member, source[member["seed"]]) for member in shared.load(path)["members"]]
        claim(receipt, {"manifest_sha256": sha(manifest), "members": rows})
        response["prepared"] = rows
    else:
        require(args.approve_evolution_reservations == evolution_cap, "approve only the remaining evolution cap")
        imported = read(receipt)
        require(imported["manifest_sha256"] == sha(manifest), "prepared manifest changed")
        for member, saved in zip(shared.load(manifest)["members"], imported["members"], strict=True):
            directory = Path(member["run_dir"])
            require(sha(directory / "checkpoint.json") == saved["checkpoint_sha256"]
                    and sha(source[member["seed"]][0] / "checkpoint.json") ==
                        sha(directory / "parent-evidence/checkpoint.json"), "source or prepared checkpoint changed")
            adapter = shared.adapter(shared.binding(manifest, directory, member["config"]))
            p = adapter.check_run(directory)
            execution.ledger(directory, read(directory / "checkpoint.json"), p, adapter=adapter)
        launched = campaign.launch(manifest, doc["execution"]["max_segments"] - 1, True, action="resume")
        response.update(submitted=True, jobs=[r["job_id"] for r in launched["initial"]["receipts"]],
                        review_job=launched["continuation"]["job_id"])
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
