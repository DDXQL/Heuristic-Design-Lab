"""Carry settled FJSP-EoH 501/502 history into the current workbench."""

import argparse
import json
from pathlib import Path
import shutil

from experiments.triad import campaign, candidate_policy, runtime, shared_admission as shared, time_continuation
from experiments.triad.obp_completion_continuation import EVIDENCE, HISTORY
from experiments.triad.obp_init_continuation import identity_only, require
from heuristic_design.core import execution
from heuristic_design.core.storage import digest, read, sha, write


OLD = "triad-candidate-runtime-20261123-r15-obp-h-feedback"
OLD_COMMIT = "ac9f467f1bf942979c3cba3ef061365842282e12"
OLD_BATCH = "candidate-lab-r15-fjsp-eoh-501-503-20261123"
OLD_MANIFEST = "7b3317ed6cb3e739595d9803957e322824bae0e8d08aca433b7461997bf7cbf0"
NEW = "triad-candidate-runtime-20261125-r15-fjsp-eoh-recovery"
NAME = "r15-fjsp-eoh-501-502-recovery"
SEEDS = {501: ("647306", 216, "SLOT-0000230"), 502: ("647307", 211, "SLOT-0000221")}
HALT = "non_retryable_unclassified_error"
EXECUTION_CHANGES = {"code/heuristic_design/core/execution.py"} | {
    "experiments/triad/" + name + ".py" for name in (
        "batch_admission", "campaign", "candidate_policy", "configuration", "evaluation",
        "obp_completion_continuation", "obp_init_continuation", "parallel", "problems",
        "runtime", "shared_admission", "time_continuation")}


def terminal_failure(journal, state, config, slot):
    task = state["tasks"][slot]
    requests, attempts = journal["requests"], journal["api_attempts"]
    require(journal["halt_reason"] == HALT and set(requests) == set(state["tasks"])
            and all(r["status"] in ("completed", "failed") for r in requests.values())
            and all(a["status"] in ("completed", "failed") and a.get("finished_at")
                    for a in attempts.values()), "unsettled requests or different terminal failure")
    ids = requests[slot]["attempt_ids"]
    require(bool(ids) and requests[slot]["status"] == "failed"
            and all(ident in attempts for ident in ids), "original rejected slot was not settled")
    failed = attempts[ids[-1]]
    meta = failed.get("metadata") or {}
    expected = config["provider"]["expected_response_model"]
    observed = meta.get("model")
    # An older V5 build retained json_decode even when decode_chat had
    # extracted a response-model label. Carry the rejection, never the content.
    require(failed["status"] == "failed" and failed["send_confirmed"] is True
            and failed.get("retryable") is False and meta.get("send_status") == "confirmed"
            and meta.get("http_status") == 200 and meta.get("failure_stage") == "json_decode"
            and meta.get("caller_hard_stop") is True and meta.get("dispatch_children_settled") is True
            and expected == "gpt-6.1-sol" and observed == "siwc/gpt-6.1-sol"
            and task.get("successful_evolution_response") is False
            and task.get("failure") == "HTTP_or_transport_failure",
            "response evidence differs from the two diagnosed rejected requests")
    require(all((a.get("metadata") or {}).get("send_status") != "unknown"
                or a["status"] == "failed" and a.get("retry_reason") == "wire_outcome_unknown_charged"
                and (a.get("metadata") or {}).get("dispatch_children_settled") is True
                for a in attempts.values()), "request delivery remains unresolved")
    return {"slot": slot, "response_model": observed, "expected_model": expected,
            "usage_unknown": failed.get("usage") is None}


def audit(root):
    old = root.parent / OLD
    path = old / "plans" / OLD_BATCH / "Shared.json"
    require(sha(path) == OLD_MANIFEST and read(old / "release.json")["engineering_commit"] == OLD_COMMIT,
            "source release or original FJSP manifest differs")
    manifest = shared.load(path)
    require(manifest["mode"] == "real" and shared.independent(manifest), "original independent FJSP batch required")
    selected = [r for r in manifest["members"] if r["seed"] in SEEDS]
    require({r["seed"] for r in selected} == set(SEEDS) and len(selected) == 2, "expected both original seeds")
    accounting = time_continuation.accounting_for({**manifest, "members": selected})
    require(all(v == {"state": "COMPLETED", "exit_code": "0:0"} for v in accounting.values()),
            "an original worker or submission is active or unresolved")
    unresolved = {read(marker)["attempt"] for marker in (path.parent / "api-pacing").glob("*.unresolved")}
    sources, receipts = {}, []
    for row in selected:
        seed = row["seed"]
        job, count, slot = SEEDS[seed]
        directory = Path(row["run_dir"]).resolve()
        config = read(row["config"])
        require(row["group"] == "fjsp-eoh" and directory.is_relative_to(old / "runs" / OLD_BATCH)
                and job in accounting and read(directory / "latest-submission.json")["job_id"] == job
                and not any((directory / name).exists() for name in
                            (".execution.lock", ".coordinator.lock", "Stop.json", "Clock_quarantine.json"))
                and not (Path(config["account_gate"]) / "generation.lock").exists(),
                "old seed identity or writer differs")
        protocol, state = runtime.protocol_state(directory)
        require(state["phase"] == "paused" and state.get("pause_reason") == "persistent API Stop: " + HALT
                and state["successful_evolution_responses"] == count
                == sum(t.get("successful_evolution_response", False) for t in state["tasks"].values())
                and state["cursor"] == len(state["tasks"]) and state["eoh"]["stage"] == "evolution"
                and state["eoh"]["np_rng"] is not None and state.get("rng") is not None
                and protocol["config"]["evolution_request_cap"] == 1000
                and sha(row["config"]) == protocol["config_sha256"]
                and sha(directory / "Run_clock.json") == state["clock_sha256"]
                and sha(directory / "Tasks.json") == protocol["tasks_sha256"], "old checkpoint differs")
        require(set(state["tasks"]) == {task["id"] for task in read(directory / "Tasks.json")[:state["cursor"]]}
                and all(t["status"] == "completed" for t in state["tasks"].values()),
                "old candidate sequence contains unfinished work")
        for name, expected in protocol["source_files"].items():
            require(sha(old / name) == expected and (name in EXECUTION_CHANGES or sha(root / name) == expected),
                    "old or current scientific source differs: " + name)
        journal = read(directory / "API_attempts.json")
        require(not unresolved.intersection(journal["api_attempts"]), "old seed still has an unresolved API worker")
        terminal = terminal_failure(journal, state, config, slot)
        costs = candidate_policy.costs(journal)["reservations_by_stage"]
        remaining = config["candidate_policy"]["evolution_attempt_cap"] - costs.get("evolution", 0)
        require(remaining > 0 and len(journal["api_attempts"]) < row["request_cap"], "reserved budget exhausted")
        sources[seed] = directory
        receipts.append({"seed": seed, "previous_job": job, "successful_evolution": count,
                         "remaining_evolution_reservations": remaining, **terminal})
    inputs = read(path.parent.with_name(OLD_BATCH + "-inputs") / "request.json")
    doc = inputs["config"]
    require(digest(doc) == inputs["config_digest"], "original user configuration differs")
    doc["name"] = NAME
    doc["research"]["runs"] = [r for r in doc["research"]["runs"] if r["seed"] in SEEDS]
    doc["execution"]["max_segments"] = campaign.authorization(path, manifest)["max_segments"] - 1
    require(doc["execution"]["max_segments"] >= 1, "no remaining original Slurm segments")
    return doc, sources, receipts


def import_member(manifest, row, old, *, pause_reason="settled API response rejected in original run"):
    original, state = runtime.protocol_state(old)
    run = Path(row["run_dir"])
    mock = original["config"]["api_mode"] == "mock"
    protocol = runtime.prepare(run, row["config"], engineering=mock, allow_api=not mock,
                               approve_budget=None if mock else row["request_cap"])
    allowed = ("account_gate", "shared_manifest", "data_manifest", "window_seconds")
    expected = {**original["config"], **{k: protocol["config"][k] for k in allowed}}
    if original["config"]["problem"] == "obp":
        expected["state_delivery"] = {**expected["state_delivery"],
                                      "file": protocol["config"]["state_delivery"]["file"]}
    require(expected == protocol["config"] and protocol["config"]["window_seconds"] is None
            and all(protocol[k] == original[k] for k in
                    ("instances", "references", "members", "budgets", "metrics", "tasks_sha256", "source_cost"))
            and protocol.get("H_prompt_contract") == original.get("H_prompt_contract"),
            "training data, search semantics or original budget changed")
    if original["config"]["problem"] == "obp":
        require(protocol["obp_execution_contract"] == original["obp_execution_contract"],
                "OBP action or reference contract changed")
    evidence = run / "parent-evidence"
    evidence.mkdir()
    for name in EVIDENCE:
        shutil.copyfile(old / name, evidence / name)
    require(read(evidence / "checkpoint.json") == state and sha(evidence / "Protocol.json") == state["identity"],
            "source state changed during import")
    for name in (*HISTORY, "plans"):
        source = old / name
        if source.is_dir():
            shutil.copytree(source, run / name)
        elif source.is_file():
            shutil.copyfile(source, run / name)
    clock = {"start": read(evidence / "Run_clock.json")["start"], "deadline": None}
    write(run / "Run_clock.json", clock)
    protocol["api_continuation"] = {"parent_protocol_sha256": state["identity"], "parent_run_id": original["run_id"],
                                    "evidence": {name: sha(evidence / name) for name in EVIDENCE}}
    write(run / "Protocol.json", protocol)
    identity = sha(run / "Protocol.json")
    (run / "Protocol.sha256").write_text(identity + "\n")
    checkpoint = {**state, "identity": identity, "clock_sha256": sha(run / "Run_clock.json"),
                  "pause_reason": pause_reason}
    write(run / "checkpoint.json", checkpoint)
    binding = shared.binding(manifest, run, row["config"])
    transport = shared.adapter(binding).transport(protocol) if mock else identity_only(protocol, binding)
    journal = candidate_policy.journal(None, run, checkpoint, protocol, None, identity_only=transport)
    previous = read(evidence / "API_attempts.json")
    journal.data.update({k: previous[k] for k in ("requests", "api_attempts")})
    journal.validate_counts()
    journal.save()
    shared.attach(run, binding)
    adapter = shared.adapter(binding)
    execution.ledger(run, checkpoint, adapter.check_run(run), adapter=adapter)


def verify_import(run, protocol):
    proof = protocol["api_continuation"]
    evidence = Path(run) / "parent-evidence"
    require(all(sha(evidence / name) == expected for name, expected in proof["evidence"].items()),
            "original recovery evidence changed")
    old = read(evidence / "API_attempts.json")
    current = read(Path(run) / "API_attempts.json")
    require(all(current[k].get(name) == record for k in ("requests", "api_attempts")
                for name, record in old[k].items()), "inherited request history changed")


def main(workbench, argv):
    parser = argparse.ArgumentParser(prog="experiment.py recover-fjsp-eoh", description=__doc__)
    parser.add_argument("--approve", action="store_true", help="submit only seeds 501/502 within their original budgets")
    args = parser.parse_args(argv)
    root = workbench.ROOT
    require(root.name == NEW, "use the separate FJSP recovery release")
    doc, sources, receipts = audit(root)
    members, preview = workbench.prepare(doc)
    require(preview["ready_for_submission_checks"], "continuation assets did not pass preflight")
    folder = root / "plans" / ("candidate-lab-" + NAME)
    result = {"source_seeds": receipts, "no_new_initialization": True, "submitted": False,
              "status_config": str(folder / "continuation-config.json")}
    if args.approve:
        workbench.check_launch_environment(members[0][0])
        manifest = workbench.create_plan(doc, folder, members, preview)
        for row in shared.load(manifest)["members"]:
            import_member(manifest, row, sources[row["seed"]])
        write(folder / "continuation-config.json", doc)
        launched = campaign.launch(manifest, doc["execution"]["max_segments"], True, action="resume",
                                   review_wall_seconds=preview["review_wall_seconds"])
        result.update(submitted=True, jobs=[r["job_id"] for r in launched["initial"]["receipts"]],
                      review_job=launched["continuation"]["job_id"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
