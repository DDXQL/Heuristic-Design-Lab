"""One-time continuation of OBP-EoH seeds 501–503 from 998 responses."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "code"), str(ROOT)]

from experiments.triad import campaign, candidate_policy, runtime, shared_admission as shared, time_continuation
from experiments.triad.concurrency_probe import claim
from experiments.triad.obp_init_continuation import identity_only, require
from heuristic_design.core import execution
from heuristic_design.core.storage import digest, read, sha, write
from tools import experiment

OLD = "triad-candidate-runtime-20261122-r15-obp-native"
SOURCE_COMMIT = "338fd073ed772d8062a7ab1ecca5a4acf11dffe6"
NEW = "triad-candidate-runtime-20261123-r15-obp-completion"
SOURCE_PLAN = "candidate-lab-r15-obp-eoh-native"
NAME = "r15-obp-eoh-completion"
REVIEW = "639712"
SEEDS = {501: ("639709", (172, 186)), 502: ("639710", (178, 487)), 503: ("639711", (234, 435))}
CHANGED = {"deploy/eoh-baseline/eoh_gap.py", "experiments/triad/candidate_runtime_tests.py"}
EVIDENCE = ("Protocol.json", "checkpoint.json", "API_attempts.json", "Run_clock.json", "latest-submission.json")
HISTORY = ("worker-receipts", "evaluations", "prompts", "responses", "wire_responses",
           "caller_rejections", "populations", "Events.jsonl")


def audit_source(parent):
    path = parent / "plans" / SOURCE_PLAN / "Shared.json"
    manifest = shared.load(path)
    result = read(path.parent / "Campaign_result.json")
    require(read(parent / "release.json")["engineering_commit"] == SOURCE_COMMIT
            and manifest["mode"] == "real" and shared.independent(manifest), "wrong source release or batch")
    require(result["reason"] == "ended_incomplete" and result["segments"] == 1
            and result["account_release"] == {"closed": True, "resume_prohibited": True}
            and read(path.parent / "Closed.json")["manifest_sha256"] == sha(path)
            and not (Path(manifest["account_gate"]) / "generation.lock").exists()
            and not (path.parent / "gate/STOP.json").exists()
            and not list((path.parent / "api-pacing").glob("*.unresolved")), "source has unresolved batch state")
    segments = campaign.authorization(path, manifest)["max_segments"] - result["segments"]
    require(segments > 0, "inherited Slurm segment cap exhausted")
    accounting = time_continuation.accounting_for(manifest)
    require(set(accounting) == {job for job, _ in SEEDS.values()}
            and all(a == {"state": "COMPLETED", "exit_code": "0:0"} for a in accounting.values()),
            "source workers are active or Slurm receipts differ")
    review = subprocess.run(["sacct", "-n", "-P", "-X", "-j", REVIEW, "--format=JobIDRaw,State,ExitCode"],
                            check=True, text=True, capture_output=True, timeout=30)
    require(review.stdout.strip() == REVIEW + "|COMPLETED|0:0", "source reviewer has not closed")

    sources = {}
    for member in manifest["members"]:
        seed = member["seed"]
        job, missed = SEEDS[seed]
        run = Path(member["run_dir"])
        cfg = read(member["config"])
        require(member["group"] == "obp-eoh" and run.is_relative_to(parent / "runs" / SOURCE_PLAN)
                and read(run / "latest-submission.json")["job_id"] == job
                and not any((run / f).exists() for f in
                            (".execution.lock", ".coordinator.lock", "Stop.json", "Clock_quarantine.json"))
                and not (Path(cfg["account_gate"]) / "generation.lock").exists(), f"seed {seed} scope or writer differs")
        protocol, state = runtime.protocol_state(run)
        require(protocol["config"]["initialization_policy"] == "native_EoH"
                and protocol["config"]["search_seed"] == seed and protocol["config"]["evolution_request_cap"] == 1000
                and state["phase"] == "completed" and state["eoh"]["stage"] == "evolution"
                and state["eoh"]["operator_cursor"] == 1000 and state["eoh"]["initialization_requests"] == 10
                and state["cursor"] == len(state["tasks"]) == 1010
                and state["successful_evolution_responses"] == 998 ==
                    sum(t.get("successful_evolution_response", False) for t in state["tasks"].values()),
                f"seed {seed} is not the diagnosed checkpoint")
        failures = {key: row["failure"] for key, row in state["tasks"].items()
                    if row.get("successful_evolution_response") is False}
        require(failures == {f"SLOT-{i:07d}": "HTTP_or_transport_failure" for i in missed},
                f"seed {seed} failed slot records differ")
        require(sha(member["config"]) == protocol["config_sha256"]
                and sha(run / "Tasks.json") == protocol["tasks_sha256"]
                and sha(run / "Run_clock.json") == state["clock_sha256"], "source config, task plan or clock differs")
        for name, expected in protocol["source_files"].items():
            require(sha(parent / name) == expected, f"source release file differs: {name}")
            if name not in CHANGED:
                require(sha(ROOT / name) == expected, f"unapproved runtime change: {name}")
        journal = read(run / "API_attempts.json")
        require(not journal["halt_reason"] and set(journal["requests"]) == set(state["tasks"])
                and all(r["status"] in ("completed", "failed") for r in journal["requests"].values())
                and all(a["status"] in ("completed", "failed") and a.get("finished_at")
                        and (a.get("metadata") or {}).get("send_status") != "unknown"
                        for a in journal["api_attempts"].values()), "source API work remains unsettled")
        spent = candidate_policy.costs(journal)["reservations_by_stage"]
        require(spent == {"initialization": 10, "evolution": 1000}
                and cfg["candidate_policy"]["evolution_attempt_cap"] - spent["evolution"] == 100,
                "inherited request reservations differ")
        time_continuation.check_calendar(cfg, read(run / "Run_clock.json"), time.time(), full_segment=False)
        sources[seed] = run
    require(set(sources) == set(SEEDS), "all three source seeds are required")
    inputs = read(path.parent.with_name(SOURCE_PLAN + "-inputs") / "request.json")
    require(digest(inputs["config"]) == inputs["config_digest"], "source workbench input differs")
    return path, sources, segments, {**inputs["config"], "name": NAME}


def import_member(manifest, row, old):
    original, state = runtime.protocol_state(old)
    directory = Path(row["run_dir"])
    mock = original["config"]["api_mode"] == "mock"
    protocol = runtime.prepare(directory, row["config"], engineering=mock,
                               allow_api=not mock, approve_budget=None if mock else row["request_cap"])
    expected = {**original["config"]}
    for key in ("account_gate", "shared_manifest", "data_manifest"):
        expected[key] = protocol["config"][key]
    expected["state_delivery"] = {**expected["state_delivery"], "file": protocol["config"]["state_delivery"]["file"]}
    require(protocol["config"] == expected and all(protocol[key] == original[key] for key in
            ("instances", "references", "members", "budgets", "metrics", "tasks_sha256",
             "obp_execution_contract", "H_prompt_contract")), "frozen experiment or physical cap changed")
    evidence = directory / "parent-evidence"
    evidence.mkdir()
    for name in EVIDENCE:
        shutil.copyfile(old / name, evidence / name)
    shutil.copyfile(old / "Run_clock.json", directory / "Run_clock.json")
    for name in HISTORY:
        path = old / name
        if path.is_dir():
            shutil.copytree(path, directory / name)
        elif path.is_file():
            shutil.copyfile(path, directory / name)
    inherited = original["obp_init_continuation"]
    protocol["obp_init_continuation"] = {
        "parent_protocol_sha256": inherited["parent_protocol_sha256"],
        "immediate_parent_protocol_sha256": state["identity"],
        "parent_run_id": original["run_id"], "parent_job_id": read(old / "latest-submission.json")["job_id"],
        "native_initialization_requests_inherited": inherited["native_initialization_requests_inherited"],
        "evidence": {name: sha(evidence / name) for name in EVIDENCE},
    }
    write(directory / "Protocol.json", protocol)
    identity = sha(directory / "Protocol.json")
    (directory / "Protocol.sha256").write_text(identity + "\n")
    checkpoint = {**state, "identity": identity, "phase": "paused",
                  "pause_reason": "audited EoH successful-response completion"}
    write(directory / "checkpoint.json", checkpoint)
    binding = shared.binding(manifest, directory, row["config"])
    transport = shared.adapter(binding).transport(protocol) if mock else identity_only(protocol, binding)
    journal = candidate_policy.journal(None, directory, checkpoint, protocol,
                                       read(directory / "Run_clock.json")["deadline"], identity_only=transport)
    previous = read(old / "API_attempts.json")
    journal.data.update({key: previous[key] for key in ("requests", "api_attempts")})
    journal.save()
    shared.attach(directory, binding)
    validate_prepared(manifest, row)
    return {"seed": row["seed"], "checkpoint_sha256": sha(directory / "checkpoint.json")}


def validate_prepared(manifest, row):
    run = Path(row["run_dir"])
    adapter = shared.adapter(shared.binding(manifest, run, row["config"]))
    protocol = adapter.check_run(run)
    execution.ledger(run, read(run / "checkpoint.json"), protocol, adapter=adapter)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "submit"))
    parser.add_argument("--approve-remaining-requests", type=int)
    args = parser.parse_args()
    require(ROOT.name == NEW, "use the designated new deployment directory")
    require(args.approve_remaining_requests == (300 if args.action == "submit" else None),
            "real submission requires explicit approval for the inherited maximum of 300 reservations")
    _, sources, segments, doc = audit_source(ROOT.parent / OLD)
    folder = ROOT / "plans" / ("candidate-lab-" + NAME)
    manifest = folder / "Shared.json"
    config = folder / "continuation-config.json"
    receipt = folder / "OBP-completion-import.json"
    result = {"seeds": sorted(sources), "starting_successes_per_seed": 998, "new_initialization": 0,
              "remaining_request_reservations": 300, "original_segments_remaining": segments,
              "status_config": str(config), "submitted": False}
    if args.action == "prepare":
        members, preview = experiment.prepare(doc, inherited_window=doc["execution"]["window_hours"] * 3600)
        require(preview["ready_for_submission_checks"], "training asset preflight did not pass")
        path = experiment.create_plan(doc, folder, members, preview)
        rows = [import_member(path, row, sources[row["seed"]]) for row in shared.load(path)["members"]]
        claim(config, doc)
        claim(receipt, {"manifest_sha256": sha(path), "members": rows})
        result["prepared"] = rows
    elif args.action == "submit":
        saved = read(receipt)
        require(saved["manifest_sha256"] == sha(manifest) and read(config) == doc, "prepared plan changed")
        for row, proof in zip(shared.load(manifest)["members"], saved["members"], strict=True):
            run = Path(row["run_dir"])
            require(row["seed"] == proof["seed"] and sha(run / "checkpoint.json") == proof["checkpoint_sha256"]
                    and all(sha(sources[row["seed"]] / name) == sha(run / "parent-evidence" / name)
                            for name in EVIDENCE), "source or prepared checkpoint changed")
            validate_prepared(manifest, row)
        launched = campaign.launch(manifest, segments, True, action="resume")
        result.update(submitted=True, jobs=[r["job_id"] for r in launched["initial"]["receipts"]],
                      review_job=launched["continuation"]["job_id"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
