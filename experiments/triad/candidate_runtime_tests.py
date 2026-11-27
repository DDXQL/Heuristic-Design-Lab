"""Offline failure injection and actual 1000-response executor simulations."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "code"), str(ROOT)]
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, TransportError
from heuristic_design.core import execution
from heuristic_design.core.storage import digest, read, sha, write
from experiments.triad import campaign, candidate_policy, entry, evaluation, problems, runtime, shared_admission as shared, six_ops, time_continuation
from experiments.triad.explore_tests import Inner, deny, fixture, refused

POLICY = ROOT / "configurations/six-groups-20261116/candidate-policy.draft.json"


def configure(folder, reference, target, *, failure_limit=5, evolution_attempt_cap=None):
    path, m, _ = fixture(folder)
    policy = read(POLICY)
    policy["evolution_attempt_cap"] = (target + max(10, target // 10)
                                       if evolution_attempt_cap is None else evolution_attempt_cap)
    policy["rate_limit_backoff_seconds"] = 1
    policy["failure_streak_limit"] = failure_limit
    m["candidate_policy"] = policy
    for row in m["members"]:
        c = six_ops.config(row["group"])
        cap = 20 + policy["evolution_attempt_cap"]
        c.update(mode="mock", freeze_status="engineering_only", search_seed=501, window_seconds=7200,
                 account_exclusion={"scope": "all_devices_sharing_account", "confirmation": "offline",
                                    "valid_until": time.time() + 14400}, credential_file=None, evaluation_concurrency=1,
                 account_gate=str(path.parent / "run-gates" / row["run_id"]),
                 reference_file=str(reference), shared_manifest=str(path), candidate_policy=policy,
                 evolution_request_cap=target, api_attempt_cap=cap, per_candidate_attempt_cap=2,
                 mock_faults={"5": "invalid", "6": "duplicate", "11": "invalid_evaluation",
                              "16": "invalid_evaluation"})
        c["resources"].update(drain_seconds=2000, request_queue_seconds=2)
        write(Path(row["config"]), c)
        row.update(request_cap=cap, config_sha256=sha(row["config"]))
        d = Path(row["run_dir"])
        (d / "checkpoint.json").unlink()
        d.rmdir()
        runtime.prepare(d, row["config"], engineering=True)
    m["total_request_cap"] = sum(row["request_cap"] for row in m["members"])
    write(path, m)
    write(Path(m["account_gate"]) / "generation.lock", {"protocol": "SHARED:" + sha(path)})
    log = path.parent / "gate/ledger.json"
    s = read(log)
    s["manifest_sha256"] = sha(path)
    write(log, s)
    for r in m["members"]:
        d = Path(r["run_dir"])
        shared.attach(d, shared.binding(path, d, r["config"]))
    return path, m


def transport_fault(code, send, stage):
    e = TransportError("offline synthetic failure")
    e.metadata = {"send_status": send, "failure_stage": stage, "http_status": code}
    if send == "not_started":
        e.metadata["temporary_network_failure"] = True
    e.usage = None
    return e


def inject(base, response_plan, calls):
    def dispatch(self, key, prompt, *, kind, on_sent):
        slot, attempt = (int(v) for v in key.rsplit("SLOT-", 1)[1].split("/attempt/"))
        c = self.p["config"]
        group = c["group"]
        calls[group, slot, attempt] = calls.get((group, slot, attempt), 0) + 1
        behavior = response_plan.get((group, slot, attempt))
        if behavior == "known_not_sent":
            raise transport_fault(None, "not_started", "connect")
        if behavior == "unknown":
            raise transport_fault(None, "unknown", "http_send")
        if isinstance(behavior, int):
            on_sent()
            raise transport_fault(behavior, "confirmed", "http_receive")
        if behavior in ("empty", "truncated"):
            on_sent()
            return {"text": "", "usage": None, "metadata": {"response_class": behavior}}
        return base(self, key, prompt, kind=kind, on_sent=on_sent)
    return dispatch


def run_member(path, row, *, resume=False, pause_at=None):
    d = Path(row["run_dir"])
    job = "910" + str(row["index"])
    b = shared.binding(path, d, row["config"])
    a = shared.adapter(b)
    original = a.task_context
    if pause_at is not None:
        def task_context(directory, state, p, task, index):
            if state.get("successful_evolution_responses", 0) == pause_at:
                a.segment_deadline = time.monotonic()
            return original(directory, state, p, task, index)
        a.task_context = task_context
    with patch.dict(os.environ, {"SLURM_JOB_ID": job}), patch.object(shared.Admission, "startup"):
        with shared.Admission(b).session(d):
            result = execution.start(d, adapter=a, resume=resume)
    return result, read(d / "checkpoint.json")


def receipt(row, job):
    d = Path(row["run_dir"])
    r = {"state": "submitted", "job_id": job, "finite_settled_prefix": None}
    write(d / "latest-submission.json", r)
    write(d / "submissions" / ("shared-mock-" + job + ".json"), r)
    return {"state": "COMPLETED", "exit_code": "0:0"}


@contextmanager
def workload_storage(fast):
    """Keep large synthetic ledgers in memory, flushing them at segment boundaries."""
    if not fast:
        yield lambda _: None
        return
    ledgers = {}
    dumps = json.dumps

    def compact(value, *args, **kwargs):
        if kwargs.get("indent") is not None:
            kwargs["indent"] = None
        return dumps(value, *args, **kwargs)

    @contextmanager
    def transaction(a):
        a.verify()
        path = a.folder / "ledger.json"
        if path not in ledgers:
            ledgers[path] = read(path)
        yield ledgers[path]

    def flush(path):
        p = path.parent / "gate/ledger.json"
        write(p, ledgers[p])

    with patch.object(json, "dumps", compact), patch.object(shared.Admission, "transaction", transaction):
        yield flush


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--fast-ledger", action="store_true", help="mock the workload's shared-ledger writes between segments")
    parser.add_argument("--boundary", choices=("tsp-u", "tsp-eoh"),
                        help="inject transport faults after 999 successful evolution responses")
    args = parser.parse_args()
    if args.boundary:
        boundary(args.boundary)
        return
    target = args.target
    assert target >= 10
    policy = read(POLICY)
    candidate_policy.validate(policy, 1000)
    refused(candidate_policy.validate, policy, 1000, real=True)
    assert entry.slurm_time_left("1-02:30:00") == 95400
    assert entry.slurm_time_left("11:33") == 693
    refused(entry.slurm_time_left, "UNLIMITED")
    # Test actual V5 normalization and policy admission without opening a socket.
    fake = object.__new__(candidate_policy.CandidateTransport)
    fake.provider = type("Provider", (), {"expected_response_model": "synthetic"})()
    error = transport_fault(200, "confirmed", "schema")
    error.metadata.update(model="synthetic", finish_reason="length", content_type="str")
    with patch.object(JsonCandidateTransport, "dispatch", side_effect=error):
        assert fake.dispatch()["metadata"]["response_class"] == "truncated"
    with patch.object(JsonCandidateTransport, "dispatch", return_value={"text": "", "metadata": {}, "usage": None}):
        assert fake.dispatch()["metadata"]["response_class"] == "empty"
    processed = ROOT / "runs"
    processed.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="OFFLINE-successful-", dir=processed) as td:
        tmp = Path(td)
        source = read(ROOT / "preparations/triad/tsp/train20.manifest.json")
        ref = tmp / "mock-reference.json"
        write(ref, {"kind": "mock-reference-v1", "engineering_only": True,
                    "instances": [{"file": x["file"], "reference": 1.0} for x in source["instances"]]})
        (tmp / "plans").mkdir()
        path, manifest = configure(tmp / "plans/candidate-e2e", ref, target)
        u, eoh = manifest["members"]
        calls = {}
        injected = {
            ("tsp-u", 5, 1): "known_not_sent",
            ("tsp-u", 6, 1): 520, ("tsp-u", 7, 1): 522, ("tsp-u", 8, 1): 524,
            ("tsp-u", 9, 1): 429, ("tsp-u", 10, 1): "empty", ("tsp-u", 11, 1): "truncated",
            ("tsp-eoh", 11, 1): "empty", ("tsp-eoh", 12, 1): "truncated",
        }
        report = {}
        with (workload_storage(args.fast_ledger) as flush,
              patch.object(socket.socket, "connect", deny), patch.object(socket, "create_connection", deny),
              patch.object(JsonCandidateTransport, "__init__", deny), patch.object(problems, "solve_row", deny),
              patch.object(evaluation, "evaluate", deny), patch.object(execution.sys, "platform", "linux"),
              patch.object(runtime.MockTransport, "dispatch", inject(runtime.MockTransport.dispatch, injected, calls)),
              patch.object(candidate_policy.CandidateJournal, "__init__", sync_journal_for_fixture),
              patch.object(runtime.Adapter, "on_commit")):
            # Backoff in this fixture is recorded, but waiting for real time or contacting Slurm is unnecessary.
            cap = min(500, target // 2)
            for row in (u, eoh):
                result, s = run_member(path, row, pause_at=cap)
                flush(path)
                assert result["phase"] == "paused", result
                assert s["pause_reason"] == candidate_policy.TIME_PAUSE and s.get("successful_evolution_responses") == cap, (
                    row["group"], s.get("pause_reason"), s.get("successful_evolution_responses"), s["cursor"],
                    (path.parent / "gate/STOP.json").read_text() if (path.parent / "gate/STOP.json").exists() else None,
                    list(read(path.parent / "gate/ledger.json")["requests"].values())[-2:])
            accounting = {"9100": receipt(u, "9100"), "9101": receipt(eoh, "9101")}
            assessed = time_continuation.inspect(path, accounting=accounting)
            assert assessed["eligible"] and assessed["selected"] == [0, 1], assessed
            controller(path, manifest, accounting, resume=True)
            for row in (u, eoh):
                d = Path(row["run_dir"])
                earlier = read(d / "checkpoint.json")
                result, s = run_member(path, row, resume=True)
                flush(path)
                assert result["phase"] == "completed", result
                assert s["successful_evolution_responses"] == target
                assert {k: s["tasks"][k] for k in earlier["tasks"]} == earlier["tasks"]
                if row["group"] == "tsp-u":
                    assert s["tasks"]["SLOT-0000005"]["failure"] == "parse_or_constraint_error"
                    assert s["tasks"]["SLOT-0000005"]["successful_evolution_response"] is True
                    assert any(t.get("AST_duplicate") and t.get("successful_evolution_response")
                               for t in s["tasks"].values())
                else:
                    assert s["eoh"]["operator_cursor"] == target + 2
                    excluded = [t["response_class"] for t in s["tasks"].values() if t["excluded_response"]]
                    assert excluded == ["empty", "truncated"]
                out = runtime.export(d)
                assert (d / "exports/API-physical-attempts.csv").is_file()
                assert (d / "exports/best-J-by-successful-response.svg").is_file()
                assert (d / "exports/frozen_engineering_candidate.json").is_file()
                report[row["group"]] = {"target": target, "final": out["successful_evolution_responses"],
                                        "settled_checkpoint": cap, "reservations": out["request_reservations"],
                                        "simulated_sends": out["physical_sends_confirmed"],
                                        "retries": out["retry_reservations"]}
            j = read(Path(u["run_dir"]) / "API_attempts.json")
            assert len(j["requests"]["SLOT-0000005"]["attempt_ids"]) == 2
            for i in range(6, 12):
                assert calls["tsp-u", i, 1] == 1 and ("tsp-u", i, 2) not in calls
            assert all(n == 1 for n in calls.values())
            s = read(path.parent / "gate/ledger.json")
            assert not s["jobs"] and not s["active"] and not (path.parent / "gate/STOP.json").exists()
            assert s["peak"] == 1 and any(r.get("send_state") == "confirmed" and r.get("usage") is None
                                          and r["state"] == "reconciled_failed" for r in s["requests"].values())
            final = time_continuation.inspect(path, accounting=accounting)
            assert final["scientific_complete"] and not final["eligible"] and not final["blockers"], final
        controller(path, manifest, accounting, resume=False)
        protections(tmp, ref)
        optional_streak(tmp, ref)
        delayed_controller_receipt(tmp)
        failed_queue_head(tmp, ref)
        timeout_with_live_peer(tmp, ref)
        unknown_send_turn(tmp, ref)
        staggered_start(tmp, ref)
        rate_limited_peer(tmp, ref)
        print(json.dumps({"passed": True, "searches": report, "real_api": 0, "real_solves": 0,
                          "real_slurm": 0, "workload_uses_mock_ledger_storage": args.fast_ledger,
                          "file_ledger_regressions": ["failed queue head", "real admission timeout with live peer",
                                                      "unknown send-turn lock", "staggered startup",
                                                      "shared 429 backoff", "unknown send"],
                          "tracked_attempts_are_not_model_results": True}, indent=2))


original_journal = candidate_policy.CandidateJournal.__init__


def sync_journal_for_fixture(self, *args, **kwargs):
    original_journal(self, *args, **kwargs)
    self.sleep = lambda _: None


def boundary(group):
    """Use a real Mock checkpoint and the on-disk ledger for each fault at the boundary."""
    # U exercises all faults with headroom. EoH independently checks a 524 on
    # the last allowed reservation, where a replacement would exceed the cap.
    cap = 1002 if group == "tsp-u" else 1000
    cases = {
        "HTTP520": (520, [1, 1], 2, "completed"),
        "HTTP522": (522, [1, 1], 2, "completed"),
        "HTTP524": (524, [1, 1], 2, "completed"),
        "HTTP429": (429, [1, 1], 2, "completed"),
        "queue_timeout_recovered": ("queue", [2], 1, "completed"),
        "queue_timeout_both_attempts": ("queue_twice", [2, 1], 1, "completed"),
        "not_sent_recovered": ("known_not_sent", [2], 1, "completed"),
        "not_sent_both_attempts": ("known_not_sent_twice", [2, 1], 1, "completed"),
        "unknown_send": ("unknown", [1], 0, "paused"),
    } if group == "tsp-u" else {
        "HTTP524_at_hard_cap": (524, [1], 1, "paused"),
    }
    processed = ROOT / "runs"
    processed.mkdir(exist_ok=True)
    with (tempfile.TemporaryDirectory(prefix="OFFLINE-candidate-boundary-", dir=processed) as td,
          patch.object(socket.socket, "connect", deny), patch.object(socket, "create_connection", deny),
          patch.object(JsonCandidateTransport, "__init__", deny), patch.object(problems, "solve_row", deny),
          patch.object(evaluation, "evaluate", deny), patch.object(execution.sys, "platform", "linux"),
          patch.object(runtime.Adapter, "on_commit")):
        tmp = Path(td)
        source = read(ROOT / "preparations/triad/tsp/train20.manifest.json")
        reference = tmp / "mock-reference.json"
        write(reference, {"kind": "mock-reference-v1", "engineering_only": True,
                          "instances": [{"file": x["file"], "reference": 1.0} for x in source["instances"]]})
        path, manifest = configure(tmp / "plan", reference, 1000, evolution_attempt_cap=cap)
        row = next(r for r in manifest["members"] if r["group"] == group)
        d = Path(row["run_dir"])
        gate = path.parent / "gate"
        with workload_storage(True) as flush:
            _, checkpoint = run_member(path, row, pause_at=999)
            flush(path)
        assert checkpoint["phase"] == "paused" and checkpoint["pause_reason"] == candidate_policy.TIME_PAUSE, checkpoint["phase"]
        assert checkpoint["successful_evolution_responses"] == 999
        journal_path = d / "API_attempts.json"
        previous = read(journal_path)
        old_costs = candidate_policy.costs(previous)
        assert old_costs["reservations_by_stage"]["evolution"] == 999
        first = checkpoint["cursor"]
        plan = read(d / "Tasks.json")
        backup = tmp / "checkpoint-at-999"
        shutil.copytree(d, backup)
        initial_ledger = read(gate / "ledger.json")
        print(json.dumps({"group": group, "baseline": 999, "evolution_reservations_cap": cap}), flush=True)

        acquire = shared.Admission.acquire
        for name, (fault, per_slot, sent, phase) in cases.items():
            shutil.rmtree(d)
            shutil.copytree(backup, d)
            write(gate / "ledger.json", initial_ledger)
            calls = {}
            fault_count = 2 if str(fault).endswith("_twice") else 1
            fault = fault.removesuffix("_twice") if isinstance(fault, str) else fault
            first_slot = int(plan[first]["id"].removeprefix("SLOT-"))
            response_plan = {(group, first_slot, n): fault for n in range(1, fault_count + 1)} if fault != "queue" else {}
            queued_keys = {f"/{plan[first]['id']}/attempt/{n:02d}" for n in range(1, fault_count + 1)} if fault == "queue" else set()

            def acquire_with_timeout(self, key):
                if not any(key.endswith(ending) for ending in queued_keys):
                    return acquire(self, key)
                # Expire only this wait. The real gate still writes and settles its waiting ticket.
                self.deadline = time.time() - 1
                try:
                    return acquire(self, key)
                finally:
                    self.deadline = None

            with (patch.object(shared.Admission, "acquire", acquire_with_timeout),
                  patch.object(runtime.MockTransport, "dispatch", inject(runtime.MockTransport.dispatch, response_plan, calls)),
                  patch.object(candidate_policy.CandidateJournal, "__init__", sync_journal_for_fixture)):
                _, final = run_member(path, row, resume=True)
            j = read(journal_path)
            costs = candidate_policy.costs(j)
            ledger = read(gate / "ledger.json")
            new_shared = [r for uid, r in ledger["requests"].items() if uid not in initial_ledger["requests"]]
            new_tasks = [task["id"] for task in plan[first:final["cursor"]]]
            expected_tasks = [task["id"] for task in plan[first:first + len(per_slot)]]
            assert new_tasks == expected_tasks, (name, new_tasks, expected_tasks)
            assert final["phase"] == phase, (name, final["phase"], final.get("pause_reason"))
            assert final["successful_evolution_responses"] == (1000 if phase == "completed" else 999), name
            assert all(j["api_attempts"][k] == v for k, v in previous["api_attempts"].items()), name
            assert set(j["requests"]) - set(previous["requests"]) == set(new_tasks), name
            assert [len(j["requests"][key]["attempt_ids"]) for key in new_tasks] == per_slot, name
            attempts = [j["api_attempts"][key] for t in new_tasks for key in j["requests"][t]["attempt_ids"]]
            assert costs["reservations_by_stage"] == {"initialization": old_costs["reservations_by_stage"]["initialization"],
                                                       "evolution": 999 + sum(per_slot)}, name
            assert costs["reservations_by_stage"]["evolution"] <= cap, name
            assert sum(a["send_confirmed"] for a in attempts) == sent, name
            assert costs["physical_sends_confirmed"] == old_costs["physical_sends_confirmed"] + sent, name
            assert len(new_shared) == len(attempts), name
            assert all(n == 1 for n in calls.values()), (name, calls)
            assert (gate / "STOP.json").exists() == (fault == "unknown"), name
            for i, attempt in enumerate(attempts):
                should_count = phase == "completed" and i == len(attempts) - 1
                assert attempt["status"] == ("completed" if should_count else "failed"), (name, attempt)
                if not should_count:
                    assert attempt["usage"] is None
            if isinstance(fault, int):
                assert attempts[0]["metadata"]["http_status"] == fault and attempts[0]["send_confirmed"]
                assert not attempts[0]["retryable"] and new_shared[0]["state"] == "reconciled_failed"
                if fault == 429:
                    assert new_shared[-1]["sent_at"] >= ledger["rate_resume_at"]
            if fault == "queue":
                assert all(a["error_type"] == "TimeoutError" and a["metadata"]["failure_stage"] == "shared_admission"
                           for a in attempts[:fault_count])
                assert set(calls) == {(group, int(new_tasks[-1].removeprefix("SLOT-")), per_slot[-1])}
            if fault in ("queue", "known_not_sent"):
                assert all(not a["send_confirmed"] and a["metadata"]["send_status"] in ("not_sent", "not_started")
                           for a in attempts[:fault_count])
                assert all(r["state"] == "reconciled_failed" for r in new_shared[:fault_count])
            if fault == "unknown":
                assert final["pause_reason"] == "persistent API Stop: unresolved_send_or_worker"
                assert costs["physical_sends_unknown"] == old_costs["physical_sends_unknown"] + 1
                assert new_shared[0]["state"] == "failed_or_unknown"
            elif phase == "paused":
                assert final["pause_reason"] == candidate_policy.BUDGET_PAUSE
                assert final["tasks"][new_tasks[-1]]["attempt_stage_exhausted"]
            if fault != "unknown":
                assert not ledger["active"] and not ledger["jobs"], name
            print(json.dumps({"case": name, "group": group, "phase": final["phase"], "pause_reason": final.get("pause_reason"),
                              "successful": final["successful_evolution_responses"], "new_slots": new_tasks,
                              "attempts_per_slot": per_slot, "new_reservations": sum(per_slot), "new_confirmed_sends": sent,
                              "evolution_reservations": costs["reservations_by_stage"]["evolution"],
                              "evolution_confirmed_sends": sum(a["send_confirmed"] for a in j["api_attempts"].values()
                                                               if j["requests"][a["logical_id"]]["stage"] == "evolution"),
                              "first_failure_usage": attempts[0]["usage"],
                              "shared_STOP": (gate / "STOP.json").exists()}), flush=True)
        print(json.dumps({"passed": True, "group": group, "cases": len(cases), "real_api": 0,
                          "real_solves": 0, "real_slurm": 0}), flush=True)


def controller(path, m, accounting, *, resume):
    # Exercise the actual durable controller claim/decision logic, with fake Slurm only.
    auth = {"manifest_sha256": sha(path), "max_segments": 2, "allow_api": False, "allow_solves": False,
            "approve_requests": m["total_request_cap"], "expires_at": time.time()+300, "release_account": False}
    write(path.parent / "Campaign_authorization.json", auth)
    worker_ids = {"receipts": [{"job_id": j} for j in accounting]}
    from types import SimpleNamespace
    segment = 1 if resume else 2
    with (patch.object(campaign, "ROOT", path.parent.parent.parent),
          patch.object(campaign, "account_when_visible", return_value=accounting),
          patch.dict(os.environ, {"SLURM_JOB_ID": "9300" if resume else "9301"})):
        if resume:
            followup = {"receipts": [{"job_id": "9100"}, {"job_id": "9101"}]}
            with (patch.object(campaign.subprocess, "run", side_effect=[SimpleNamespace(stdout="9300\n"), SimpleNamespace(stdout="9301\n")]) as sbatch,
                  patch.object(campaign.parallel, "submit", return_value=followup) as fake_resume):
                r = campaign.queue_followup(path, 1, worker_ids)
                assert r["job_id"] == "9300" and "--dependency=afterany:9100:9101" in sbatch.call_args.args[0]
                refused(campaign.queue_followup, path, 1, worker_ids)
                result = campaign.advance(path, segment)
                assert result["submitted"] and result["next"]["job_id"] == "9301"
                assert fake_resume.call_count == 1 and sbatch.call_count == 2
        else:
            result = campaign.advance(path, segment)
            assert result["reason"] == "scientific_complete" and not result["submitted"]
        refused(campaign.advance, path, segment)


def protections(tmp, ref):
    path, m = configure(tmp / "candidate-unknown", ref, 10)
    row = m["members"][0]
    calls = {}
    base = runtime.MockTransport.dispatch
    with (patch.object(socket.socket, "connect", deny), patch.object(execution.sys, "platform", "linux"),
          patch.object(runtime.MockTransport, "dispatch", inject(base, {("tsp-u", 0, 1): "unknown"}, calls))):
        _, current = run_member(path, row)
    s = read(path.parent / "gate/ledger.json")
    assert current["phase"] in ("paused", "stopped")
    assert (path.parent / "gate/STOP.json").exists() and s["active"]
    assert len(s["requests"]) == 1 and calls == {("tsp-u", 0, 1): 1}


def optional_streak(tmp, ref):
    path, m = configure(tmp / "candidate-streak-off", ref, 10, failure_limit=0)
    row = m["members"][0]
    faults = {("tsp-u", slot, 1): 524 for slot in range(6)}
    calls = {}
    with (patch.object(socket.socket, "connect", deny), patch.object(execution.sys, "platform", "linux"),
          patch.object(runtime.MockTransport, "dispatch", inject(runtime.MockTransport.dispatch, faults, calls))):
        result, current = run_member(path, row)
    assert result["phase"] == "completed" and current["successful_evolution_responses"] == 10
    assert not (path.parent / "gate/STOP.json").exists()
    assert all(calls["tsp-u", slot, 1] == 1 and ("tsp-u", slot, 2) not in calls for slot in range(6))


def delayed_controller_receipt(tmp):
    f = tmp / "review.json"
    write(f, {"state": "submission_reserved"})
    refused(campaign.controller_receipt, f, 0)
    launched = {"state": "submitted", "job_id": "9302"}
    with patch.object(campaign.time, "sleep", side_effect=lambda _: write(f, launched)):
        assert campaign.controller_receipt(f) == launched


def failed_queue_head(tmp, ref):
    path, m = configure(tmp / "candidate-abandoned-waiter", ref, 10)
    u, peer = m["members"]
    a = shared.Admission(shared.binding(path, u["run_dir"], u["config"]))
    b = shared.Admission(shared.binding(path, peer["run_dir"], peer["config"]))
    failed = Inner()

    def interrupted_acquire(key):
        uid = digest({"member": a.member, "key": key})
        with a.transaction() as s:
            s["requests"][uid] = {"member": a.member, "key": key, "ticket": s["next_ticket"],
                                  "state": "waiting", "reserved_at": time.time()}
            s["next_ticket"] += 1
        raise OSError("offline: failure after a waiting reservation was saved")

    with patch.object(shared.Admission, "startup"):
        with a.session(u["run_dir"]), patch.object(a, "acquire", side_effect=interrupted_acquire):
            try:
                shared.GuardedTransport(failed, a).dispatch("waiter", "offline", kind="u", on_sent=lambda: None)
            except OSError as error:
                assert error.metadata["send_status"] == "not_sent"
            else:
                raise AssertionError("queue failure not propagated")
        with b.session(peer["run_dir"]):
            reply = shared.GuardedTransport(Inner(), b).dispatch("peer", "offline", kind="h", on_sent=lambda: None)
            assert reply["text"] == "SYNTHETIC"
    data = read(path.parent / "gate/ledger.json")
    assert failed.calls == 0 and not data["active"] and not data["jobs"]
    assert [r["state"] for r in data["requests"].values()] == ["reconciled_failed", "completed"]
    assert not (path.parent / "gate/STOP.json").exists()


def timeout_with_live_peer(tmp, ref):
    path, m = configure(tmp / "candidate-timeout-active-peer", ref, 10)
    u, peer = m["members"]
    a = shared.Admission(shared.binding(path, u["run_dir"], u["config"]))
    b = shared.Admission(shared.binding(path, peer["run_dir"], peer["config"]))
    timed_out = Inner()
    turn = path.parent / "gate/send-turn.lock"
    ledger = path.parent / "gate/ledger.json"

    class PeerHoldingTurn(Inner):
        def dispatch(self, key, prompt, *, kind, on_sent):
            holder = read(turn)
            assert holder["member"] == b.member and read(ledger)["active"] == {holder["uid"]: b.member}
            a.deadline = time.time() + 0.05
            try:
                shared.GuardedTransport(timed_out, a).dispatch("timeout", "offline", kind="u", on_sent=lambda: None)
            except TimeoutError as error:
                assert "request admission wait exceeded" in str(error) and error.metadata["send_status"] == "not_sent"
            else:
                raise AssertionError("request did not time out while queued")
            assert read(turn) == holder
            assert not (path.parent / "gate/STOP.json").exists()
            return super().dispatch(key, prompt, kind=kind, on_sent=on_sent)

    with patch.object(shared.Admission, "startup"), a.session(u["run_dir"]), b.session(peer["run_dir"]):
        first = shared.GuardedTransport(PeerHoldingTurn(), b)
        assert first.dispatch("peer-held", "offline", kind="h", on_sent=lambda: None)["text"] == "SYNTHETIC"
        second = shared.GuardedTransport(Inner(), b)
        assert second.dispatch("peer-next", "offline", kind="h", on_sent=lambda: None)["text"] == "SYNTHETIC"
    s = read(ledger)
    rejected = next(r for r in s["requests"].values() if r["key"] == "timeout")
    assert rejected["state"] == "reconciled_failed" and rejected["send_state"] == "not_sent" and timed_out.calls == 0
    assert len(s["requests"]) == 3 and s["peak"] == 1 and not s["active"] and not s["jobs"] and not turn.exists()


def staggered_start(tmp, ref):
    path, m = configure(tmp / "candidate-staggered-start", ref, 10)
    identity = "offline-staggered-allocation"
    jobs = {r["run_id"]: str(9400 + r["index"]) for r in m["members"]}
    write(path.parent / "Current_allocation.json", {"state": "submitted", "identity": identity,
                                                    "manifest_sha256": sha(path), "jobs": jobs})
    preflight = path.parent / "preflight" / identity
    for row in m["members"]:
        role = row["index"]
        if role == 0:
            assert not (preflight / "startup-pass-1.json").exists()
        b = shared.binding(path, row["run_dir"], row["config"])
        with patch.dict(os.environ, {"SLURM_JOB_ID": jobs[row["run_id"]]}), shared.Admission(b).session(row["run_dir"]):
            outcome = read(preflight / f"startup-pass-{role}.json")
            assert outcome["job_id"] == jobs[row["run_id"]] and outcome["scope"] == "one_job_local_probe"
            assert not (path.parent / "gate/STOP.json").exists()


def unknown_send_turn(tmp, ref):
    path, m = configure(tmp / "candidate-orphan-send-turn", ref, 10)
    row = m["members"][0]
    a = shared.Admission(shared.binding(path, row["run_dir"], row["config"]))
    turn = path.parent / "gate/send-turn.lock"
    unknown = {"member": "unknown", "uid": "unmatched"}
    write(turn, unknown)
    inner = Inner()
    with patch.object(shared.Admission, "startup"), a.session(row["run_dir"]):
        a.deadline = time.time() + 0.2
        refused(shared.GuardedTransport(inner, a).dispatch, "cannot-send", "offline", kind="u", on_sent=lambda: None)
        assert inner.calls == 0 and read(turn) == unknown
        assert (path.parent / "gate/STOP.json").exists()


def rate_limited_peer(tmp, ref):
    path, m = configure(tmp / "candidate-rate-limit", ref, 10)
    u, peer = m["members"]
    a = shared.Admission(shared.binding(path, u["run_dir"], u["config"]))
    b = shared.Admission(shared.binding(path, peer["run_dir"], peer["config"]))
    r = Inner("http429")
    good = Inner()
    with patch.object(shared.Admission, "startup"), a.session(u["run_dir"]), b.session(peer["run_dir"]):
        refused(shared.GuardedTransport(r, a).dispatch, "limited", "offline", kind="u", on_sent=lambda: None)
        not_before = read(path.parent / "gate/ledger.json")["rate_resume_at"]
        assert not_before > time.time()
        shared.GuardedTransport(good, b).dispatch("peer-after-backoff", "offline", kind="h", on_sent=lambda: None)
        assert time.time() >= not_before
    data = read(path.parent / "gate/ledger.json")
    assert r.calls == good.calls == 1 and len(data["requests"]) == 2
    assert not (path.parent / "gate/STOP.json").exists()


if __name__ == "__main__":
    main()
