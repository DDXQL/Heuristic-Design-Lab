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
from experiments.triad import campaign, candidate_policy, entry, evaluation, parallel, problems, runtime, shared_admission
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
            return SimpleNamespace(stdout="00:45:00\n")
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
    fixture = "tsp-502" if kind in ("automatic", "parallel8", "serial_control") else "slurm-no-api-smoke"
    doc = cli.read(cli.ROOT / f"configurations/experiments/{fixture}.json")
    doc["name"] = label
    doc["execution"]["mode"] = "mock"
    doc["execution"]["api"]["min_interval_seconds"] = 0
    doc["research"]["budget"]["target"] = 5
    if kind in ("automatic", "parallel8", "serial_control"):
        doc["execution"]["api"]["timeout_seconds"] = 45
        source = cli.read(cli.ROOT / doc["research"]["training_manifest"])
        reference = temporary / "TSP-mock-reference.json"
        cli.write(reference, {"kind": "mock-reference-v1", "engineering_only": True,
                              "instances": [{"file": row["file"], "reference": 1.0} for row in source["instances"]]})
        doc["research"]["reference"] = str(reference)
        doc["research"]["runs"][0]["seed"] = 800
        doc["research"]["runs"][1]["seed"] = 801

    if kind == "parallel8":
        doc["research"]["runs"] = [{"method": "u", "seed": seed, "initialization_attempts": 20}
                                   for seed in (501, 502, 503)]
        doc["execution"]["api"]["global_concurrency"] = 8
    if kind == "serial_control":
        doc["research"]["runs"] = [{"method": "u", "seed": 503, "initialization_attempts": 20}]
    if kind in ("parallel8", "serial_control"):
        doc["research"]["budget"]["target"] = 12
    if kind == "budget":
        doc["execution"]["api"]["evolution_reservation_cap"] = 5
    config = temporary / (label + ".json")
    cli.write(config, doc)
    _, folder = cli.load_document(config)
    fake = LocalSlurm()
    try:
        preview = invoke("prepare", config)
        assert preview["ready_for_submission_checks"] and not folder.exists(), preview
        assert not invoke("run", config)["submitted"] and not fake.commands
        with (patch.object(cli.shutil, "which", return_value="/offline/scheduler"),
              patch.object(cli.subprocess, "run", side_effect=fake.run)):
            launch = invoke("run", config, "--approve")
            manifest = Path(launch["manifest"])
            rows = shared_admission.load(manifest)["members"]
            assert cli.read(folder / "Campaign_authorization.json")["allow_api"] is False
            receipt = invoke("status", config)
            assert [r["job"] for r in receipt["members"]] == launch["jobs"]
            assert "--dependency=afterany:" + ":".join(launch["jobs"]) in fake.commands[launch["first_review_job"]]
            if kind == "parallel8":
                return concurrent_fixture(fake, manifest, rows, launch, config, temporary)
            if kind == "serial_control":
                final = fake.worker(manifest, rows[0], "run")
                assert final["phase"] == "completed" and final["successful_evolution_responses"] == 12
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
                assert invoke("status", config)["account_closed"]
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
            for row in rows:
                final = fake.worker(manifest, row, "resume")
                later = cli.read(Path(row["run_dir"]) / "API_attempts.json")
                assert final["phase"] == "completed" and final["successful_evolution_responses"] == 5
                assert all(later["api_attempts"][k] == a for k, a in prior[row["run_id"]]["api_attempts"].items())
                if kind == "automatic":
                    p, _ = runtime.protocol_state(row["run_dir"])
                    assert candidate_policy.client_config(p).provider.total_timeout == 45
                    assert p["config"]["client_binding"]["provider"]["total_timeout"] == 300
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


def concurrent_fixture(fake, manifest, rows, launch, config, temporary):
    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(3, timeout=20)
    peak, active = ctx.Value("i", 0), ctx.Value("i", 0)
    transport = runtime.MockTransport.dispatch

    def dispatch(self, key, prompt, *, kind, on_sent):
        seed = self.p["config"]["search_seed"]
        with active.get_lock():
            active.value += 1
            peak.value = max(peak.value, active.value)
        try:
            if key.endswith("SLOT-0000000/attempt/01"):
                barrier.wait()
            if key.endswith("SLOT-0000005/attempt/01"):
                if seed == 501:
                    on_sent()
                    raise transport_fault(524, "confirmed", "http_receive")
                if seed == 502:
                    raise transport_fault(None, "unknown", "http_send")
            return transport(self, key, prompt, kind=kind, on_sent=on_sent)
        finally:
            with active.get_lock():
                active.value -= 1

    def worker(row):
        try:
            fake.worker(manifest, row, "run")
        except Exception:
            import traceback
            traceback.print_exc()
            raise

    with patch.object(runtime.MockTransport, "dispatch", dispatch):
        processes = [ctx.Process(target=worker, args=(row,)) for row in rows]
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
    assert peak.value == 3, peak.value
    for job in launch["jobs"]:
        fake.accounting[job] = True
    ending = fake.review(manifest, 1, launch["first_review_job"])
    assert ending["reason"] == "scientific_complete"
    results = {}
    for row in rows:
        d = Path(row["run_dir"])
        checkpoint = cli.read(d / "checkpoint.json")
        assert checkpoint["successful_evolution_responses"] == 12 and checkpoint["generation"] >= 1
        journal = cli.read(d / "API_attempts.json")
        costs = candidate_policy.costs(journal)
        assert costs["reservations_by_stage"]["evolution"] == (12 if row["seed"] == 503 else 13)
        assert costs["physical_sends_unknown"] == int(row["seed"] == 502)
        failed = [a for a in journal["api_attempts"].values() if a["status"] == "failed"]
        assert len(failed) == int(row["seed"] != 503)
        if failed:
            assert failed[0]["number"] == 1 and failed[0]["usage"] is None and not failed[0]["retryable"]
        assert journal["halt_reason"] is None
        for generation in (d / "plans").glob("G*.json"):
            frozen = cli.read(generation)
            ids = {p["id"] for p in frozen["parents"]}
            for task in checkpoint["tasks"].values():
                if task.get("original_generation") == frozen["generation"]:
                    assert set(task["parents"]).issubset(ids)
        results[str(row["seed"])] = {"successful": 12, **costs}
        if row["seed"] == 503:
            healthy = population_trace(checkpoint)
    assert not (manifest.parent / "gate/ledger.json").exists()
    assert not (manifest.parent / "gate/STOP.json").exists()
    assert (manifest.parent / "Closed.json").exists()
    invoke("export", config, "--out", str(temporary / "parallel8.zip"))
    return {"configured": 8, "observed_peak": peak.value, "members": results, "healthy": healthy}


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
                assert "/public2/home/qiuqian/hdl-envs/portable-v2/bin/python" in menu
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


if __name__ == "__main__":
    with (tempfile.TemporaryDirectory() as directory,
          patch.object(socket.socket, "connect", deny), patch.object(socket, "create_connection", deny),
          patch.object(JsonCandidateTransport, "__init__", deny), patch.object(cli.subprocess, "run", deny),
          patch.object(problems, "solve_row", deny), patch.object(evaluation, "evaluate", deny),
          patch.object(execution, "sys", SimpleNamespace(platform="linux"))):
        report = {kind: run_case(kind, Path(directory)) for kind in ("automatic", "operator", "budget", "parallel8")}
        assert report["parallel8"].pop("healthy") == run_case("serial_control", Path(directory))
        report["parallel8"]["healthy_seed_matches_serial_population_and_rng"] = True
        report["permit_probe_peak"] = permits8(Path(directory) / "permits8")
        report["wizard"] = wizard_cases(Path(directory))
        print(json.dumps({**report, "real_api": 0, "real_solves": 0, "slurm_submissions": 0}, indent=2))
