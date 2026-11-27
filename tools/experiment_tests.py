"""Offline regression of the researcher CLI with local workers and simulated Slurm."""

from contextlib import redirect_stdout
import io
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
from threading import Lock, Barrier
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import zipfile

import experiment as cli
from r15_results import summarize
from experiments.triad import campaign, candidate_policy, entry, evaluation, parallel, post_evaluation, problems, runtime, shared_admission, six_ops
from experiments.triad.candidate_runtime_tests import transport_fault
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, response_audit
from experiments.triad.batch_admission import Permits, retry_after
from heuristic_design.core import execution


def deny(*args, **kwargs):
    raise AssertionError("real API, solver or scheduler process is forbidden")


def invoke(action, config, *args):
    with redirect_stdout(io.StringIO()) as output:
        cli.main([action, str(config), *args])
    return json.loads(output.getvalue())


class LocalSlurm:
    def __init__(self):
        self.commands = {}
        self.accounting = {}

    def run(self, command, **kwargs):
        if command[0] == "sbatch":
            job = str(9900 + len(self.commands))
            self.commands[job] = command
            return SimpleNamespace(stdout=job + "\n")
        if command[0] == "sacct":
            ids = command[command.index("-j") + 1].split(",")
            return SimpleNamespace(stdout="".join(f"{j}|COMPLETED|0:0\n" for j in ids if j in self.accounting))
        if command[0] == "squeue":
            return SimpleNamespace(stdout="02:00:00\n")
        if str(cli.ROOT / "experiments/triad/entry.py") in command:
            index = command.index(str(cli.ROOT / "experiments/triad/entry.py"))
            with patch.object(sys, "argv", command[index:]), redirect_stdout(io.StringIO()) as output:
                assert entry.main() == 0, output.getvalue()
            return SimpleNamespace(stdout=output.getvalue())
        return deny(command)

    def worker(self, manifest, row, action):
        d = Path(row["run_dir"])
        job = cli.read(d / "latest-submission.json")["job_id"]
        with patch.dict(os.environ, {"SLURM_JOB_ID": job}):
            self.run(parallel.argv(row, action, manifest))
        self.accounting[job] = True
        return cli.read(d / "checkpoint.json")

    def review(self, manifest, number, job):
        with patch.dict(os.environ, {"SLURM_JOB_ID": job}):
            result = campaign.advance(manifest, number)
        self.accounting[job] = True
        return result


def run_case(kind, temporary):
    label = f"offline-{uuid4().hex[:12]}"
    fixture = {"fjsp": "fjsp-503", "obp": "obp-501", "automatic": "tsp-502",
               "parallel8": "r15p5-site-no-api", "serial_control": "r15p5-site-no-api"}.get(kind, "slurm-no-api-smoke")
    doc = cli.read(cli.ROOT / f"configurations/experiments/{fixture}.json")
    doc["name"] = label
    doc["execution"]["mode"] = "mock"
    doc["execution"]["api"]["min_interval_seconds"] = 0
    if kind not in ("parallel8", "serial_control"):
        doc["research"]["budget"]["target"] = 5
    if kind == "fjsp":
        assert cli.prepare(cli.read(cli.ROOT / "configurations/experiments/fjsp-503.json"))[1]["ready_for_submission_checks"]
    if kind == "obp":
        members, preview = cli.prepare(cli.read(cli.ROOT / "configurations/experiments/obp-501.json"))
        assert preview["members"][0]["pending"] and not preview["members"][1]["pending"]
        from dataclasses import asdict
        h_file = temporary / (label + "-synthetic-H.json")
        hs = [asdict(problems.validate_h("obp", "def priority(item_size, remaining_capacities):\n"
                                       f"    return [{i} + cap for cap in remaining_capacities]\n"))
              for i in range(10)]
        cli.write(h_file, {"engineering_only": True, "members": hs})
        doc["research"]["frozen_h"] = str(h_file)
    if kind in ("automatic", "parallel8", "serial_control"):
        doc["execution"]["api"]["timeout_seconds"] = 45
        source = cli.read(cli.ROOT / doc["research"]["training_manifest"])
        reference = temporary / "TSP-mock-reference.json"
        cli.write(reference, {"kind": "mock-reference-v1", "engineering_only": True,
                              "instances": [{"file": row["file"], "reference": 1.0} for row in source["instances"]]})
        doc["research"]["reference"] = str(reference)
    if kind == "automatic":
        doc["research"]["runs"][0]["seed"] = 800
        doc["research"]["runs"][1]["seed"] = 801
        doc["execution"]["slurm"]["review_wall_seconds"] = 1800
    if kind == "serial_control":
        doc["research"]["runs"] = doc["research"]["runs"][-1:]
    if kind == "budget":
        doc["execution"]["api"]["evolution_reservation_cap"] = 5
    config = temporary / (label + ".json")
    cli.write(config, doc)
    _, folder = cli.load_document(config)
    fake = LocalSlurm()
    try:
        preview = invoke("prepare", config)
        assert preview["ready_for_submission_checks"] and not folder.exists(), preview
        review_seconds = 1800 if kind == "automatic" else 3600
        assert preview["review_wall_seconds"] == review_seconds
        unstarted = invoke("status", config)["members"]
        assert [m["seed"] for m in unstarted] == [r["seed"] for r in doc["research"]["runs"]]
        assert all(m["phase"] == "not_started" and m["successful_evolution"] == 0
                   and m["target"] == doc["research"]["budget"]["target"] for m in unstarted)
        assert not folder.exists()
        assert not invoke("run", config)["submitted"] and not fake.commands
        with (patch.object(cli.shutil, "which", return_value="/offline/scheduler"),
              patch.object(cli.subprocess, "run", side_effect=fake.run)):
            launch = invoke("run", config, "--approve")
            manifest = Path(launch["manifest"])
            rows = shared_admission.load(manifest)["members"]
            assert cli.read(folder / "Campaign_authorization.json")["allow_api"] is False
            receipt = invoke("status", config)
            assert [r["job"] for r in receipt["members"]] == launch["jobs"]
            assert receipt["review_job"] == launch["first_review_job"] and receipt["review_state"] == "submitted"
            assert receipt["review_wall_seconds_at_submission"] == review_seconds
            assert f"--time={review_seconds // 60}" in fake.commands[launch["first_review_job"]]
            for row, status in zip(rows, receipt["members"]):
                checkpoint = Path(row["run_dir"]) / "checkpoint.json"
                assert status["checkpoint_updated_at"] == checkpoint.stat().st_mtime
                assert Path(status["logs"]["out"]).name == f'{row["run_id"]}-{status["job"]}.out'
            assert "--dependency=afterany:" + ":".join(launch["jobs"]) in fake.commands[launch["first_review_job"]]
            if kind == "parallel8":
                return concurrent_fixture(fake, manifest, rows, launch, config, temporary)
            if kind == "serial_control":
                final = fake.worker(manifest, rows[0], "run")
                assert final["phase"] == "completed" and final["successful_evolution_responses"] == 20
                return population_trace(final)
            if kind == "budget":
                dispatch = runtime.MockTransport.dispatch

                def terminal_failure(self, key, prompt, *, kind, on_sent):
                    checkpoint = cli.read(Path(rows[0]["run_dir"]) / "checkpoint.json")
                    if checkpoint["eoh"]["stage"] == "evolution":
                        on_sent()
                        raise transport_fault(524, "confirmed", "http_receive")
                    return dispatch(self, key, prompt, kind=kind, on_sent=on_sent)

                with patch.object(runtime.MockTransport, "dispatch", terminal_failure):
                    stopped = fake.worker(manifest, rows[0], "run")
                assert stopped["pause_reason"] == candidate_policy.BUDGET_PAUSE
                result = fake.review(manifest, 1, launch["first_review_job"])
                assert result["reason"] == "ended_incomplete" and result["account_release"]["closed"]
                receipt = invoke("status", config)
                assert receipt["account_closed"]
                failed_status = receipt["members"][0]
                checkpoint = Path(rows[0]["run_dir"]) / "checkpoint.json"
                assert failed_status["checkpoint_updated_at"] == checkpoint.stat().st_mtime
                assert failed_status["api_failed_attempts"] == 5 and failed_status["confirmed_sends"] == 0
                assert failed_status["mock_sends"] >= 5 and failed_status["valid_candidates"] > 0
                assert failed_status["candidate_failures"] >= 5
                incomplete = invoke("export", config, "--out", str(temporary / (label + ".zip")))
                assert incomplete["members_exported"] == [rows[0]["run_id"]]
                return {"outcome": result["reason"], "account_closed": True}
            if kind == "operator":
                original = runtime.Adapter.on_commit

                def request_pause(self, d, state, protocol):
                    original(self, d, state, protocol)
                    if state.get("successful_evolution_responses") == 2:
                        assert invoke("pause", config)["pause_requested"] == [rows[0]["run_id"]]

                with patch.object(runtime.Adapter, "on_commit", request_pause):
                    first = fake.worker(manifest, rows[0], "run")
                assert first["phase"] == "paused" and first["pause_reason"] == "user_control", first["phase"]
            else:
                original = runtime.Adapter.task_context

                def near_deadline(self, d, state, protocol, task, index):
                    if state.get("successful_evolution_responses") == 2:
                        self.segment_deadline = time.monotonic()
                    return original(self, d, state, protocol, task, index)

                with patch.object(runtime.Adapter, "task_context", near_deadline):
                    for row in rows:
                        first = fake.worker(manifest, row, "run")
                        assert first["phase"] == "paused" and first["pause_reason"] == candidate_policy.TIME_PAUSE
            prior = {r["run_id"]: cli.read(Path(r["run_dir"]) / "API_attempts.json") for r in rows}
            if kind == "automatic":
                # Age a real-format Mock clock beyond the former 48-hour window.
                for row in rows:
                    d = Path(row["run_dir"])
                    file = d / "Run_clock.json"
                    clock = cli.read(file)
                    assert clock["deadline"] is None
                    cli.write(file, {**clock, "start": clock["start"] - 3 * 86400})
                    cp = d / "checkpoint.json"
                    cli.write(cp, {**cli.read(cp), "clock_sha256": cli.sha(file)})
            next_segment = fake.review(manifest, 1, launch["first_review_job"])
            if kind == "operator":
                assert next_segment["reason"] == "operator_paused"
                assert invoke("status", config)["outcome"] == "operator_paused"
                next_segment = invoke("resume", config)
                try:
                    invoke("resume", config)
                except PermissionError:
                    pass
                else:
                    raise AssertionError("duplicate continuation was accepted")
            assert next_segment["submitted"]
            if kind == "automatic":
                requested_wall = next(arg for arg in fake.commands[launch["jobs"][0]] if arg.startswith("--time="))
                assert all(requested_wall in fake.commands[j] for j in next_segment["next"]["workers"])
            assert next_segment["next"]["wall_seconds"] == review_seconds
            assert f"--time={review_seconds // 60}" in fake.commands[next_segment["next"]["job_id"]]
            for row in rows:
                final = fake.worker(manifest, row, "resume")
                later = cli.read(Path(row["run_dir"]) / "API_attempts.json")
                assert final["phase"] == "completed" and final["successful_evolution_responses"] == 5
                assert all(later["api_attempts"][k] == a for k, a in prior[row["run_id"]]["api_attempts"].items())
                if kind == "automatic":
                    p, _ = runtime.protocol_state(row["run_dir"])
                    assert candidate_policy.client_config(p).provider.total_timeout == 45
                    assert p["config"]["client_binding"]["provider"]["total_timeout"] == 300
                if kind == "fjsp" and row["group"] == "fjsp-u":
                    p, _ = runtime.protocol_state(row["run_dir"])
                    saved = cli.read(Path(row["run_dir"]) / "plans/G0001.json")
                    assert p["state_schema"] == "common-state-a-v3-fjsp" and len(p["members"]) == 10
                    assert {r["rule"] for r in p["references"]} == {"LB_v5"}
                    assert len(saved["parents"]) == 5 and [t["operator"] for t in saved["tasks"]] == ["CROSS", "MUTATE"] * 5
            result = fake.review(manifest, 2, next_segment["next"]["job_id"])
            assert result["reason"] == "scientific_complete" and result["account_release"]["closed"]
            zipped = invoke("export", config, "--out", str(temporary / (label + ".zip")))
            with zipfile.ZipFile(zipped["archive"]) as archive:
                assert archive.testzip() is None
                assert json.loads(archive.read("batch-status.json"))["outcome"] == "scientific_complete"
                assert sum(n.endswith("/API-physical-attempts.csv") for n in archive.namelist()) == len(rows)
            return {"outcome": result["reason"], "completed": [5] * len(rows), "segments": 2}
    finally:
        for directory in (folder, folder.with_name(folder.name + "-inputs"), cli.ROOT / "runs" / folder.name):
            if directory.is_dir():
                shutil.rmtree(directory)


def population_trace(checkpoint):
    return {"population": [member["candidate"]["key"] for member in checkpoint["population"]],
            "generation": checkpoint["generation"],
            "parents": [task["parents"] for task in checkpoint["tasks"].values()],
            "u_rng": checkpoint["u_rng"]}


def cross_batch(temporary, mode):
    """Exercise two batch starts under one account and overlapping Mock resumes."""
    owner = temporary / f"{mode}-old-account" / "generation.lock"
    old_owner = {"protocol": "existing R13 batch"}
    cli.write(owner, old_owner)
    credential = temporary / f"{mode}-credential-metadata"
    credential.touch(mode=0o600)
    original_config = cli.six_ops.config

    def same_account(group):
        config = original_config(group)
        return {**config, "account_gate": str(owner.parent), "credential_file": str(credential)}

    configs, folders = [], []
    fake = LocalSlurm()
    try:
        for problem in ("fjsp", "obp"):
            doc = cli.read(cli.ROOT / f"configurations/experiments/r15-{problem}-eoh-long.json")
            doc["name"] = f"offline-cross-{mode}-{problem}-{uuid4().hex[:8]}"
            doc["research"]["runs"] = doc["research"]["runs"][:1]
            doc["execution"]["mode"] = mode
            if mode == "mock":
                doc["research"]["budget"]["target"] = 5
                doc["execution"]["api"].update(min_interval_seconds=0, evolution_reservation_cap=5)
            config_path = temporary / (doc["name"] + ".json")
            cli.write(config_path, doc)
            configs.append(config_path)
            folders.append(cli.load_document(config_path)[1])

        with (patch.object(cli.six_ops, "config", side_effect=same_account),
              patch.object(cli.shutil, "which", return_value="/offline/scheduler"),
              patch.object(cli.subprocess, "run", side_effect=fake.run)):
            launches = [invoke("run", config, "--approve") for config in configs]
            manifests = [Path(launch["manifest"]) for launch in launches]
            plans = [shared_admission.load(manifest) for manifest in manifests]
            rows = [plan["members"][0] for plan in plans]
            owners = [Path(plan["account_gate"]) / "generation.lock" for plan in plans]
            dirs = [Path(row["run_dir"]) for row in rows]
            assert len(set(owners)) == len(set(dirs)) == 2
            for manifest, lock in zip(manifests, owners):
                assert lock == manifest.parent / shared_admission.BATCH_GATE_DIR / "generation.lock"
                assert lock.is_file()
            assert cli.read(owner) == old_owner and [row["seed"] for row in rows] == [501, 501]
            assert plans[0]["total_request_cap"] == plans[1]["total_request_cap"] == (25 if mode == "mock" else 1120)
            try:
                invoke("run", configs[0], "--approve")
            except ValueError as error:
                assert "批次名称已使用" in str(error)
            else:
                raise AssertionError("duplicate batch submission was accepted")
            assert len(fake.commands) == 4
            if mode == "real":
                assert all(cli.read(d / "checkpoint.json")["phase"] == "prepared" for d in dirs)
                assert not any((d / "API_attempts.json").exists() for d in dirs)
                return {"planned_batches": 2, "old_account_lock_preserved": True}

            ctx = multiprocessing.get_context("fork")
            barrier = ctx.Barrier(2, timeout=15)
            transport = runtime.MockTransport.dispatch
            task_context = runtime.Adapter.task_context

            def drain(adapter, directory, state, protocol, task, index):
                if state.get("successful_evolution_responses") == 2:
                    adapter.segment_deadline = time.monotonic()
                return task_context(adapter, directory, state, protocol, task, index)

            def worker(manifest, row, action):
                first = True

                def dispatch(obj, *args, **kwargs):
                    nonlocal first
                    if first:
                        first = False
                        barrier.wait()
                    return transport(obj, *args, **kwargs)

                with patch.object(runtime.MockTransport, "dispatch", dispatch):
                    fake.worker(manifest, row, action)

            def run_workers(action, jobs):
                workers = [ctx.Process(target=worker, args=(manifest, row, action))
                           for manifest, row in zip(manifests, rows)]
                for process in workers:
                    process.start()
                try:
                    for process, job in zip(workers, jobs):
                        process.join(35)
                        assert process.exitcode == 0, (action, job, process.exitcode)
                        fake.accounting[job] = True
                finally:
                    for process in workers:
                        if process.is_alive():
                            process.terminate()
                            process.join()

            with patch.object(runtime.Adapter, "task_context", drain):
                run_workers("run", [launch["jobs"][0] for launch in launches])
            checkpoints = [cli.read(d / "checkpoint.json") for d in dirs]
            assert all(cp["phase"] == "paused" and cp["pause_reason"] == candidate_policy.TIME_PAUSE
                       and cp["successful_evolution_responses"] == 2 for cp in checkpoints)
            attempts = [cli.read(d / "API_attempts.json")["api_attempts"] for d in dirs]
            resumed = [fake.review(manifest, 1, launch["first_review_job"])["next"]
                       for manifest, launch in zip(manifests, launches)]
            assert all(lock.is_file() for lock in owners)
            run_workers("resume", [result["workers"][0] for result in resumed])
            logs = [next(flag for flag in cmd if flag.startswith("--output=")).replace("%j", job)
                    for job, cmd in fake.commands.items()]
            assert len(logs) == len(set(logs)) == 8
            for index, (manifest, d, config, row, result, prior) in enumerate(
                    zip(manifests, dirs, configs, rows, resumed, attempts)):
                closed = fake.review(manifest, 2, result["job_id"])
                assert closed["reason"] == "scientific_complete" and not owners[index].exists()
                if index == 0:
                    assert owners[1].is_file(), "closing one batch removed the other batch's lock"
                checkpoint = cli.read(d / "checkpoint.json")
                assert checkpoint["phase"] == "completed" and checkpoint["successful_evolution_responses"] == 5
                assert cli.read(d / "Protocol.json")["config"]["search_seed"] == 501
                journal = cli.read(d / "API_attempts.json")
                assert all(journal["api_attempts"][key] == value for key, value in prior.items())
                assert candidate_policy.costs(journal)["reservations_by_stage"]["evolution"] == 5
                output = invoke("export", config, "--out", str(temporary / f"cross-batch-{index}.zip"))
                assert output["members_exported"] == [row["run_id"]]
                with zipfile.ZipFile(output["archive"]) as archive:
                    assert archive.testzip() is None
                    assert {n.split("/")[0] for n in archive.namelist() if "/" in n} == {row["run_id"]}
            assert cli.read(owner) == old_owner
            return {"overlapping_batches": 2, "successful_per_batch": [5, 5], "segments_each": 2,
                    "isolated_checkpoints_logs_budgets_exports": True, "old_account_lock_preserved": True}
    finally:
        for folder in folders:
            for directory in (folder, folder.with_name(folder.name + "-inputs"), cli.ROOT / "runs" / folder.name):
                if directory.is_dir():
                    shutil.rmtree(directory)


def concurrent_fixture(fake, manifest, rows, launch, config, temporary):
    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(3, timeout=20)
    peak, active = ctx.Value("i", 0), ctx.Value("i", 0)
    transport = runtime.MockTransport.dispatch
    pace = Permits.pace

    def dispatch(self, key, prompt, *, kind, on_sent):
        seed = self.p["config"]["search_seed"]
        with active.get_lock():
            active.value += 1
            peak.value = max(peak.value, active.value)
        try:
            if key.endswith("SLOT-0000000/attempt/01"):
                barrier.wait()
            if key.endswith("SLOT-0000005/attempt/01"):
                if seed == 901:
                    on_sent()
                    raise transport_fault(524, "confirmed", "http_receive")
                if seed == 902:
                    raise transport_fault(None, "unknown", "http_send")
            return transport(self, key, prompt, kind=kind, on_sent=on_sent)
        finally:
            with active.get_lock():
                active.value -= 1

    def worker(row, action):
        pacing_calls = 0

        def pace_with_failures(self, deadline, cooldown=None):
            nonlocal pacing_calls
            pacing_calls += 1
            if row["seed"] == 902 and action == "run" and pacing_calls in (7, 8):
                raise TimeoutError("local API pacing queue timeout")
            return pace(self, deadline, cooldown)

        try:
            with patch.object(Permits, "pace", pace_with_failures):
                fake.worker(manifest, row, action)
        except Exception:
            import traceback
            traceback.print_exc()
            raise

    def workers(action):
        processes = [ctx.Process(target=worker, args=(row, action)) for row in rows]
        for process in processes:
            process.start()
        try:
            for process in processes:
                process.join(45)
                assert process.exitcode == 0, process.exitcode
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()

    task_context = runtime.Adapter.task_context

    def drain_first_segment(self, directory, state, protocol, task, index):
        if state.get("successful_evolution_responses") == 3:
            self.segment_deadline = time.monotonic()
        return task_context(self, directory, state, protocol, task, index)

    with patch.object(runtime.MockTransport, "dispatch", dispatch):
        with patch.object(runtime.Adapter, "task_context", drain_first_segment):
            workers("run")
        for row, job in zip(rows, launch["jobs"]):
            saved = cli.read(Path(row["run_dir"]) / "checkpoint.json")
            assert saved["phase"] == "paused" and saved["pause_reason"] == candidate_policy.TIME_PAUSE
            assert saved["successful_evolution_responses"] == 3
            fake.accounting[job] = True
        followup = fake.review(manifest, 1, launch["first_review_job"])
        assert followup["submitted"] and len(followup["next"]["workers"]) == 3
        workers("resume")
    for job in followup["next"]["workers"]:
        fake.accounting[job] = True
    assert peak.value == 3, peak.value
    ending = fake.review(manifest, 2, followup["next"]["job_id"])
    assert ending["reason"] == "scientific_complete"
    results = {}
    expected_failures = {901: 1, 902: 3, 903: 0}
    for row in rows:
        d = Path(row["run_dir"])
        checkpoint = cli.read(d / "checkpoint.json")
        assert checkpoint["successful_evolution_responses"] == 20 and checkpoint["generation"] >= 1
        journal = cli.read(d / "API_attempts.json")
        costs = candidate_policy.costs(journal)
        seed = row["seed"]
        assert costs["reservations_by_stage"]["evolution"] == 20 + expected_failures[seed]
        assert costs["physical_sends_unknown"] == int(seed == 902)
        failed = [a for a in journal["api_attempts"].values() if a["status"] == "failed"]
        assert len(failed) == expected_failures[seed]
        assert all(a["number"] == 1 and a["usage"] is None for a in failed)
        assert sum(a["metadata"]["send_status"] == "not_sent" for a in failed) == (2 if seed == 902 else 0)
        assert journal["halt_reason"] is None
        for generation in (d / "plans").glob("G*.json"):
            frozen = cli.read(generation)
            ids = {p["id"] for p in frozen["parents"]}
            for task in checkpoint["tasks"].values():
                if task.get("original_generation") == frozen["generation"]:
                    assert set(task["parents"]).issubset(ids)
        results[str(row["seed"])] = {"successful": 20, **costs}
        if seed == 903:
            healthy = population_trace(checkpoint)
    assert not (manifest.parent / "gate/ledger.json").exists()
    assert not (manifest.parent / "gate/STOP.json").exists()
    assert (manifest.parent / "Closed.json").exists()
    invoke("export", config, "--out", str(temporary / "parallel8.zip"))
    return {"configured": 8, "observed_peak": peak.value, "segments": ending["segments"],
            "members": results, "healthy": healthy}


def permits8(folder):
    permit = Permits(folder, 8, 5, 0)
    ready = Barrier(9)
    active = peak = 0
    lock = Lock()

    def task(_):
        nonlocal active, peak
        ready.wait()
        with permit.slot(time.monotonic() + 5):
            with lock:
                active += 1
                peak = max(active, peak)
            time.sleep(.2)
            with lock:
                active -= 1

    with ThreadPoolExecutor(9) as pool:
        list(pool.map(task, range(9)))
    assert peak == 8, peak
    provider = type("Response", (), {"status": 429,
                    "getheader": lambda self, key: "123" if key == "Retry-After" else None})()
    assert retry_after(response_audit(provider)["retry_after"], time.time()) == 123
    permit.pace(time.monotonic() + .3, cooldown=.2)
    try:
        permit.pace(time.monotonic() + .05)
    except TimeoutError:
        pass
    else:
        raise AssertionError("cooldown must block sends")
    return peak


def holdout_cases(folder, mode="auto"):
    label = f"offline-holdout-{uuid4().hex[:10]}"
    folder = folder / mode
    folder.mkdir()
    cfg = folder / "holdout.json"
    doc = cli.read(cli.ROOT / "configurations/experiments/tsp-502.json")
    doc["name"] = label
    doc["execution"]["mode"] = "mock"
    doc["execution"]["api"]["min_interval_seconds"] = 0
    doc["research"]["budget"]["target"] = 5
    doc["research"]["runs"] = [{"method": "u", "seed": seed, "initialization_attempts": 20} for seed in (501, 502)]
    training = cli.ROOT / doc["research"]["training_manifest"]
    source = cli.read(training)
    train_ref = folder / "train-reference.json"
    cli.write(train_ref, {"kind": "mock-reference-v1", "instances": [
        {"file": row["file"], "reference": 1.0} for row in source["instances"]]})
    doc["research"]["reference"] = str(train_ref)
    manifest = folder / "test.manifest.json"
    reference = folder / "test-reference.json"
    doc["research"]["holdout"] = {"mode": mode, "split": "test", "manifest": str(manifest),
                                  "reference": str(reference)}
    cli.write(cfg, doc)
    _, batch = cli.load_document(cfg)
    assert not invoke("prepare", cfg)["ready_for_submission_checks"]
    first = cli.read(training.parent / source["instances"][0]["path"])
    test = folder / "relabeled.json"

    def write_manifest():
        cli.write(manifest, {"problem": "tsp", "split": "test",
                             "instances": [{"file": test.name, "path": test.name, "sha256": cli.sha(test)}]})

    cli.write(test, first)
    write_manifest()
    cli.write(reference, {"kind": "mock-reference-v1", "instances": [{"file": test.name, "reference": 1.0}]})
    assert invoke("prepare", cfg)["holdout"]["pending"] == ["holdout contains training instances"]
    first["coordinates"][0][0] = 0.123456789
    cli.write(test, first)
    write_manifest()
    assert invoke("prepare", cfg)["holdout"]["binding"]["solve_limit_per_initial_attempt"] == 2
    fake = LocalSlurm()
    try:
        with (patch.object(cli.shutil, "which", return_value="/offline/scheduler"),
              patch.object(cli.subprocess, "run", side_effect=fake.run)):
            launch = invoke("run", cfg, "--approve")
            manifest_path = Path(launch["manifest"])
            rows = shared_admission.load(manifest_path)["members"]
            for row in rows:
                fake.worker(manifest_path, row, "run")
            protected = {
                f: f.read_bytes() for row in rows for f in
                (Path(row["run_dir"]) / name for name in ("checkpoint.json", "API_attempts.json"))
            }
            result = fake.review(manifest_path, 1, launch["first_review_job"])
            assert result["reason"] == "scientific_complete" and result["account_release"]["closed"]
            state = invoke("status", cfg)
            assert state["lifecycle"]["training_complete"] and state["lifecycle"]["champions_frozen"]
            assert not state["lifecycle"]["experiment_complete"]
            if mode == "manual":
                assert all(item["holdout"]["phase"] == "ready" for item in state["members"])
                assert len(invoke("evaluate", cfg)["holdout_jobs"]) == 2
                state = invoke("status", cfg)
            holdout_jobs = [item["holdout"]["job"] for item in state["members"]]
            assert len(set(holdout_jobs)) == len(rows) == 2
            assert all("--cpus-per-task=2" in fake.commands[job] for job in holdout_jobs)

            def post(run_id, job, directory):
                with patch.dict(os.environ, {"SLURM_JOB_ID": job}):
                    return post_evaluation.run_holdout(manifest_path, run_id, directory)

            done = post_evaluation.attempts(manifest_path, rows[0]["run_id"])[0]
            initial = post(rows[0]["run_id"], holdout_jobs[0], done)
            assert initial["complete"] and initial["engineering_only"] and initial["API_requests"] == 0
            # The other allocation was interrupted before an evaluation result was committed.
            fake.accounting[holdout_jobs[1]] = True
            before_resume = invoke("status", cfg)
            assert before_resume["members"][1]["holdout"]["phase"] == "interrupted"
            partial_zip = folder / "partial-holdout.zip"
            invoke("export", cfg, "--out", str(partial_zip))
            with zipfile.ZipFile(partial_zip) as archive:
                import csv
                groups = list(csv.DictReader(archive.read("method-summary.csv").decode().splitlines()))
                assert len(groups) == 1 and groups[0]["holdout_complete_seeds"] == "1"
                assert groups[0]["holdout_mean_J"] == ""
            jobs = invoke("evaluate", cfg)["holdout_jobs"]
            assert len(jobs) == 1 and jobs[0]["run_id"] == rows[1]["run_id"]
            assert not any(r["state"] == "submitted" for r in invoke("evaluate", cfg)["holdout_jobs"])
            retry = post_evaluation.attempts(manifest_path, rows[1]["run_id"])[-1]
            original = reference.read_bytes()
            cli.write(reference, {"kind": "mock-reference-v1", "instances": [{"file": test.name, "reference": 2.0}]})
            try:
                post(rows[1]["run_id"], jobs[0]["job_id"], retry)
            except ValueError as exc:
                assert str(exc) == "holdout inputs changed since launch"
                assert not (retry / "result.json").exists()
            else:
                raise AssertionError("evaluation accepted a mutated frozen reference")
            finally:
                reference.write_bytes(original)
            fake.accounting[jobs[0]["job_id"]] = True
            jobs = invoke("evaluate", cfg)["holdout_jobs"]
            retry = post_evaluation.attempts(manifest_path, rows[1]["run_id"])[-1]
            assert post(rows[1]["run_id"], jobs[0]["job_id"], retry)["complete"]
            after = invoke("status", cfg)
            assert after["lifecycle"]["experiment_complete"] and (batch / "holdout/method-summary.csv").is_file()
            assert all(path.read_bytes() == raw for path, raw in protected.items())
            archive_path = folder / "complete-holdout.zip"
            invoke("export", cfg, "--out", str(archive_path))
            with zipfile.ZipFile(archive_path) as archive:
                assert {post_evaluation.PLAN, "seed-results.csv", "method-summary.csv",
                        "holdout-per-instance.csv"} <= set(archive.namelist())
                assert any(name.endswith("/champion.py") for name in archive.namelist())
                assert any(name.endswith("/champion_identity.json") for name in archive.namelist())
            return {"queued_jobs": len(holdout_jobs), "evaluation_only_retry": len(jobs),
                    "frozen_inputs_enforced": True, "training_files_identical": True,
                    "automatic_tables": True, "complete": True}
    finally:
        for path in (batch, batch.parent / (batch.name + "-inputs"), cli.ROOT / "runs" / batch.name):
            if path.exists():
                shutil.rmtree(path)


def holdout_problem_adapters(folder):
    # Parse synthetic holdout rows and verify the same LB/R_code used in training.
    cases = {
        "fjsp": ("mini.fjsp", b"NAME: mini\nTYPE: FJSP\nJOBS: 1\nMACHINES: 1\nJOB_SECTION\n1 1 1 5\n", "LB_v5", 5),
        "obp": ("mini.json", b'{"capacity": 10,"items": [4, 3, 2],"N": 3}', None, 1),
    }
    verified = {}
    for problem, (filename, raw, rule, known_reference) in cases.items():
        work = folder / ("held-" + problem)
        work.mkdir()
        instance = work / filename
        instance.write_bytes(raw)
        manifest = work / "test.manifest.json"
        cli.write(manifest, {"problem": problem, "split": "test", "instances": [
            {"file": filename, "path": filename, "sha256": cli.sha(instance)}]})
        c = six_ops.config(problem + "-eoh")
        spec = {"mode": "auto", "split": "test", "manifest": str(manifest), "reference": None}
        _, rows, refs, bound = post_evaluation.inputs(spec, c, [])
        assert bound["instances"] == 1 and rows[0]["split"] == "test"
        assert refs[0]["reference"] == known_reference
        if rule is not None:
            assert refs[0]["rule"] == rule and problems.decode_fjsp(rows[0], "test").operation_count == 1
        verified[problem] = refs[0]["reference"]
    return verified


def wizard_cases(folder):
    cases = {
        "tsp": {"方法": "u", "逗号": "501,502,503", "同批": "8", "每种子 Slurm": "3"},
        "fjsp": {"方法": "eoh"},
        "obp": {"方法": "u"},
    }
    reports = {}
    for problem, overrides in cases.items():
        for platform in ("local", "cluster"):
            output = folder / f"{problem}-{platform}.json"

            def answer(prompt):
                if prompt.startswith("问题"):
                    return problem
                return next((value for prefix, value in overrides.items() if prompt.startswith(prefix)), "")

            with patch("builtins.input", answer), redirect_stdout(io.StringIO()) as printed:
                cli.main(["configure", "--platform", platform, "--out", str(output)])
            doc = cli.read(output)
            assert doc["research"]["problem"] == problem
            preview = invoke("prepare", output)
            menu = printed.getvalue()
            assert "tools/experiment.py prepare" in menu
            if platform == "local":
                assert sys.executable in menu and " --approve" not in menu
            else:
                assert "$HOME/hdl-envs/portable-v2/bin/python" in menu
            if problem == "tsp":
                assert [r["seed"] for r in doc["research"]["runs"]] == [501, 502, 503]
                assert doc["execution"]["slurm"]["cpus"] == 3 and preview["global_API_width"] == 8
            elif problem == "fjsp":
                assert doc["research"]["runs"][0]["method"] == "eoh" and preview["ready_for_submission_checks"]
                assert (" --approve" in menu) == (platform == "cluster")
            elif problem == "obp":
                assert "H401" in menu and not preview["ready_for_submission_checks"] and " --approve" not in menu
            reports[f"{problem}-{platform}"] = "passed"
    return reports


def result_exports(folder):
    def build(label, group, states, *, mode="real", version="successful-evolution-responses-v1"):
        path = folder / f"{label}.zip"
        batch = {"batch": label, "mode": mode, "members": []}
        problem, method = group.split("-")
        with zipfile.ZipFile(path, "x") as archive:
            for seed, (phase, count, attempts, best) in enumerate(states, 501):
                run_id = f"{label}-{seed}"
                batch["members"].append(dict(group=group, seed=seed, run_id=run_id, phase=phase,
                                             successful_evolution=count, target=1000))
                archive.writestr(f"{run_id}/summary.json", json.dumps({
                    "run_id": run_id, "problem": problem, "method": method, "phase": phase,
                    "engineering_only": mode == "mock", "candidate_policy_version": version,
                    "successful_evolution_target": 1000, "successful_evolution_responses": count,
                    "evolution_attempts": attempts, "best_J": best,
                }))
            archive.writestr("batch-status.json", json.dumps(batch))
        return path

    complete = [("completed", 1000, 1003, 0.25), ("completed", 1000, 1001, 0.5),
                ("completed", 1000, 1000, 0.75)]
    incomplete = [("completed", 1000, 1010, 0.5), ("paused", 999, 1000, 0.1),
                  ("completed", 1000, 1001, None)]
    u = build("formal-u", "tsp-u", complete)
    eoh = build("formal-eoh", "tsp-eoh", incomplete)
    report = summarize([u, eoh])
    ir, cr = report["groups"]
    assert ir["included_seeds"] == [501] and ir["missing_or_excluded_seeds"] == [502, 503]
    assert ir["sample_std_training_J"] is None and not ir["complete_three_seed_comparison"]
    assert [row["exclusion"] for row in ir["members"]] == [
        None, "search_incomplete", "no_valid_training_champion"]
    assert cr["complete_three_seed_comparison"] and cr["included_seeds"] == [501, 502, 503]
    assert cr["mean_training_J"] == 0.5 and cr["sample_std_training_J"] == 0.25
    mock = build("mock", "tsp-u", complete, mode="mock")
    legacy = build("legacy", "tsp-u", complete, version=None)
    for archives, expected in (([mock], "Mock export"), ([legacy], "R15 candidate accounting"),
                               ([u, u], "multiple snapshots")):
        try:
            summarize(archives)
        except ValueError as error:
            assert expected in str(error), error
        else:
            raise AssertionError(f"report accepted {archives}")
    return "passed"


def dashboard_cases(folder):
    from tools import experiment_dashboard as dashboard

    project = folder / "dashboard-fixture"
    reports = project / "reports"
    reports.mkdir(parents=True)
    decisions = project / "DECISIONS.md"
    decisions.write_text("protected")
    original = project / "historical-r13"
    current = project / "new-r15"
    run = current / "runs/fixture"
    run_id = "same-experiment-id"
    paths = {}
    for version, root in (("R13", original), ("R15", current)):
        manifest = root / "plans/experiment/Shared.json"
        directory = root / "runs/fixture"
        directory.mkdir(parents=True)
        manifest.parent.mkdir(parents=True)
        config = directory / "config.json"
        ckpt = directory / "checkpoint.json"
        cli.write(config, {"data_manifest": "train20.manifest.json", "evolution_request_cap": 1000})
        cli.write(ckpt, {"phase": "completed", "eoh": {"operator_cursor": 1000},
                         "successful_evolution_responses": 998, "identity": version})
        cli.write(manifest, {"mode": "real", "candidate_policy": {"version": 1} if version == "R15" else None,
                             "members": [{"seed": 501, "group": "tsp-u", "run_id": run_id,
                                          "config": str(config), "run_dir": str(directory)}]})
        paths[version] = manifest
    cp = run / "checkpoint.json"
    before = cp.read_bytes()
    with redirect_stdout(io.StringIO()) as preview:
        dashboard.main(project, ["--root", str(original), "--root", str(current), "--format", "json"])
    rows = json.loads(preview.getvalue())["records"]
    assert {(r["version"], r["count"]) for r in rows} == {("R15", 998), ("R13", 1000)}
    assert not list(reports.iterdir()) and cp.read_bytes() == before
    assert "已结束，未核实达标" in dashboard.render(rows, [], project)

    frozen = {"champion_sha256": "c", "champion_id": "winner", "training_J": 0.1}
    plan = {"manifest": "confirm.json", "binding": {"instances": 1}, "split": "test"}
    exports = run / "exports"
    exports.mkdir()
    cli.write(exports / "frozen_training_champion.json", {})
    cli.write(cp, {**cli.read(cp), "successful_evolution_responses": 1000})
    stable = cp.read_bytes()
    attempt = paths["R15"].parent / "holdout" / run_id / "attempt-01"
    attempt.mkdir(parents=True)
    with (patch.object(dashboard.post_evaluation, "training_export", return_value=(None, None, None, frozen)),
          patch.object(dashboard.post_evaluation, "plan", return_value=plan), redirect_stdout(io.StringIO())):
        cli.write(attempt / "result.json", {"complete": True, "engineering_only": False, "rows": [{}],
                  "holdout_J": 0.2, "identity": {"wrong": True}, "split": "test", "binding": plan["binding"]})
        dashboard.main(project, ["--root", str(current), "--refresh"])
        assert "单种子齐" not in (reports / dashboard.REPORT).read_text().split("| TSP U", 1)[1]
        cli.write(attempt / "result.json", {**cli.read(attempt / "result.json"), "identity": frozen})
        dashboard.main(project, ["--root", str(current), "--refresh"])
    result = cli.read(reports / dashboard.CACHE)
    assert result["records"][0]["holdout_J"] == 0.2
    assert "| 单种子齐 |" in (reports / dashboard.REPORT).read_text()
    with redirect_stdout(io.StringIO()) as cached:
        dashboard.main(project, ["--root", str(folder / "unmounted")])
    assert "不可读，保留已有回执" in cached.getvalue() and "完成 · 历史回执" in cached.getvalue()
    assert result == cli.read(reports / dashboard.CACHE) and cp.read_bytes() == stable
    conflict = {}
    for identity in ("old", "new"):
        dashboard.blend(conflict, {**result["records"][0], "protocol_hash": identity})
    assert len(conflict) == 2
    assert decisions.read_text() == "protected"
    assert {p.name for p in reports.iterdir()} == {dashboard.REPORT, dashboard.CACHE}
    return {"separate_protocols": True, "count_verified_separately": True,
            "foreign_holdout_rejected": True, "stale_and_read_only": True}


def json_decode_and_resume(folder):
    from experiments.triad import api_continuation
    from fjsp_usage.research_real.real_transport import TransportError

    doc = cli.read(cli.ROOT / "configurations/experiments/fjsp-503.json")
    doc["name"] = "offline-eoh-decode-" + uuid4().hex[:8]
    doc["research"]["runs"] = [r for r in doc["research"]["runs"] if r["method"] == "eoh"]
    doc["research"]["budget"]["target"] = 5
    doc["execution"]["mode"] = "mock"
    doc["execution"]["api"]["min_interval_seconds"] = 0
    doc["execution"]["api"]["consecutive_failed_slots"] = 0
    config = folder / (doc["name"] + ".json")
    cli.write(config, doc)
    batch = cli.load_document(config)[1]
    target = batch.with_name(batch.name + "-continued")
    original_dispatch = runtime.MockTransport.dispatch
    faults = []

    def dispatch(self, key, prompt, *, kind, on_sent):
        state = cli.read(directory / "checkpoint.json")
        if state["eoh"]["stage"] != "evolution" or len(faults) >= 2:
            return original_dispatch(self, key, prompt, kind=kind, on_sent=on_sent)
        on_sent()
        error = TransportError("malformed response envelope")
        error.metadata = {"http_status": 200, "failure_stage": "json_decode", "caller_hard_stop": True}
        if not faults:
            error.metadata["failure_subtype"] = "invalid_json_response"
        else:
            error.metadata["model"] = "siwc/gpt-6.1-sol"
        faults.append(key)
        raise error

    fake = LocalSlurm()
    try:
        with (patch.object(cli.shutil, "which", return_value="/offline/scheduler"),
              patch.object(cli.subprocess, "run", side_effect=fake.run)):
            launch = invoke("run", config, "--approve")
            old_manifest = Path(launch["manifest"])
            old, = shared_admission.load(old_manifest)["members"]
            directory = Path(old["run_dir"])
            with patch.object(runtime.MockTransport, "dispatch", dispatch):
                paused = fake.worker(old_manifest, old, "run")
            journal = cli.read(directory / "API_attempts.json")
            old_files = {n: (directory / n).read_bytes() for n in api_continuation.EVIDENCE}
            failures = [a for a in journal["api_attempts"].values() if a["status"] == "failed"]
            assert [(a["retry_reason"], a["retryable"]) for a in failures] == [
                ("invalid_json_response_charged", False), (api_continuation.HALT, False)]
            assert len(faults) == 2 and faults[0] != faults[1] and paused["phase"] == "paused"
            source = cli.read(old["config"])
            api_continuation.terminal_failure(journal, paused, source, failures[-1]["logical_id"])
            members, preview = cli.prepare(doc)
            manifest = cli.create_plan(doc, target, members, preview)
            member, = shared_admission.load(manifest)["members"]
            api_continuation.import_member(manifest, member, directory)
            imported = cli.read(Path(member["run_dir"]) / "checkpoint.json")
            for key in ("rng", "eoh", "cursor", "tasks", "evaluations", "successful_evolution_responses"):
                assert imported.get(key) == paused.get(key)
            campaign.launch(manifest, 2, True, action="resume")
            finished = fake.worker(manifest, member, "resume")
            assert finished["phase"] == "completed" and finished["successful_evolution_responses"] == 5
            assert finished["eoh"]["initialization_requests"] == paused["eoh"]["initialization_requests"]
            assert all((directory / n).read_bytes() == data for n, data in old_files.items())
            assert cli.read(Path(member["run_dir"]) / "API_attempts.json")["halt_reason"] is None
            return {"ordinary_response_only_failed_the_slot": True, "model_check_retained": True,
                    "original_state_untouched": True, "continued_to_mock_target": True}
    finally:
        for name in (batch, target):
            for path in (name, name.with_name(name.name + "-inputs"), cli.ROOT / "runs" / name.name):
                if path.is_dir():
                    shutil.rmtree(path)


def obp_u_time_pause_import(folder):
    from dataclasses import asdict
    from experiments.triad import api_continuation

    doc = cli.read(cli.ROOT / "configurations/experiments/obp-501.json")
    doc["name"] = "offline-obp-u-adopt-" + uuid4().hex[:8]
    doc["research"]["runs"] = doc["research"]["runs"][:1]
    doc["research"]["budget"]["target"] = 5
    h_file = folder / "obp-u-import-H.json"
    hs = [asdict(problems.validate_h("obp", "def priority(item_size, remaining_capacities):\n"
                                   f"    return [{i} + cap for cap in remaining_capacities]\n"))
          for i in range(10)]
    cli.write(h_file, {"engineering_only": True, "members": hs})
    doc["research"]["frozen_h"] = str(h_file)
    doc["execution"]["mode"] = "mock"
    doc["execution"]["max_segments"] = 1
    doc["execution"]["api"]["min_interval_seconds"] = 0
    config = folder / (doc["name"] + ".json")
    cli.write(config, doc)
    batch = cli.load_document(config)[1]
    target = batch.with_name(batch.name + "-continued")
    fake = LocalSlurm()
    original = runtime.Adapter.task_context

    def near_deadline(at_count):
        def context(self, d, s, p, task, index):
            if s.get("successful_evolution_responses") == at_count:
                self.segment_deadline = time.monotonic()
            return original(self, d, s, p, task, index)
        return context

    try:
        with (patch.object(cli.shutil, "which", return_value="/offline/scheduler"),
              patch.object(cli.subprocess, "run", side_effect=fake.run)):
            launch = invoke("run", config, "--approve")
            old_manifest = Path(launch["manifest"])
            old, = shared_admission.load(old_manifest)["members"]
            old_run = Path(old["run_dir"])
            with patch.object(runtime.Adapter, "task_context", near_deadline(2)):
                paused = fake.worker(old_manifest, old, "run")
            assert paused["pause_reason"] == candidate_policy.TIME_PAUSE
            result = fake.review(old_manifest, 1, launch["first_review_job"])
            assert result["reason"] == "authorized_limits_reached" and result["account_release"]["closed"]
            original_files = {n: (old_run / n).read_bytes() for n in api_continuation.EVIDENCE}
            doc["name"] += "-continued"
            doc["execution"]["max_segments"] = None
            members, preview = cli.prepare(doc)
            manifest = cli.create_plan(doc, target, members, preview)
            member, = shared_admission.load(manifest)["members"]
            api_continuation.import_member(manifest, member, old_run, pause_reason=candidate_policy.TIME_PAUSE)
            imported = Path(member["run_dir"])
            cp = cli.read(imported / "checkpoint.json")
            for key in ("u_rng", "u_plan", "cursor", "tasks", "evaluations", "population", "eoh"):
                assert cp[key] == paused[key]
            assert sorted(p.name for p in (imported / "plans").iterdir()) == sorted(
                p.name for p in (old_run / "plans").iterdir())
            launched = campaign.launch(manifest, None, True, action="resume")
            with patch.object(runtime.Adapter, "task_context", near_deadline(3)):
                advanced = fake.worker(manifest, member, "resume")
            assert advanced["successful_evolution_responses"] == 3
            next_segment = fake.review(manifest, 1, launched["continuation"]["job_id"])
            assert next_segment["submitted"] and next_segment["next"]["segment"] == 2
            done = fake.worker(manifest, member, "resume")
            assert done["phase"] == "completed" and done["successful_evolution_responses"] == 5
            assert done["eoh"]["initialization_requests"] == paused["eoh"]["initialization_requests"]
            report = fake.review(manifest, 2, next_segment["next"]["job_id"])
            assert report["reason"] == "scientific_complete"
            assert all((old_run / n).read_bytes() == data for n, data in original_files.items())
    finally:
        for name in (batch, target):
            for path in (name, name.with_name(name.name + "-inputs"), cli.ROOT / "runs" / name.name):
                if path.is_dir():
                    shutil.rmtree(path)
    return {"same_population_rng_and_budget": True, "continued_across_segments": True}


if __name__ == "__main__":
    with (tempfile.TemporaryDirectory() as directory,
          patch.object(socket.socket, "connect", deny), patch.object(socket, "create_connection", deny),
          patch.object(JsonCandidateTransport, "__init__", deny), patch.object(cli.subprocess, "run", deny),
          patch.object(problems, "solve_row", deny), patch.object(evaluation, "evaluate", deny),
          patch.object(execution, "sys", SimpleNamespace(platform="linux"))):
        report = {kind: run_case(kind, Path(directory)) for kind in ("automatic", "operator", "budget", "parallel8", "fjsp", "obp")}
        assert report["parallel8"].pop("healthy") == run_case("serial_control", Path(directory))
        report["parallel8"]["healthy_seed_matches_serial_population_and_rng"] = True
        report["permit_probe_peak"] = permits8(Path(directory) / "permits8")
        report["cross_batch"] = {mode: cross_batch(Path(directory), mode) for mode in ("real", "mock")}
        report["wizard"] = wizard_cases(Path(directory))
        report["r15_result_exports"] = result_exports(Path(directory))
        report["post_training"] = {mode: holdout_cases(Path(directory), mode) for mode in ("auto", "manual")}
        report["post_training_reference_rules"] = holdout_problem_adapters(Path(directory))
        report["dashboard"] = dashboard_cases(Path(directory))
        report["api_recovery"] = json_decode_and_resume(Path(directory))
        report["obp_u_time_pause_import"] = obp_u_time_pause_import(Path(directory))
        print(json.dumps({**report, "real_api": 0, "real_solves": 0, "slurm_submissions": 0}, indent=2))
