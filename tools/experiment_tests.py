"""Offline regression of the researcher CLI with local workers and simulated Slurm."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import zipfile

import experiment as cli
from experiments.triad import campaign, candidate_policy, entry, evaluation, parallel, problems, runtime, shared_admission
from experiments.triad.candidate_runtime_tests import transport_fault
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
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
    fixture = "tsp-502" if kind == "automatic" else "slurm-no-api-smoke"
    doc = cli.read(cli.ROOT / f"configurations/experiments/{fixture}.json")
    doc["name"] = label
    doc["execution"]["mode"] = "mock"
    doc["execution"]["api"]["min_interval_seconds"] = 0
    doc["research"]["budget"]["target"] = 5
    if kind == "automatic":
        doc["execution"]["api"]["timeout_seconds"] = 45
        source = cli.read(cli.ROOT / doc["research"]["training_manifest"])
        reference = temporary / "TSP-mock-reference.json"
        cli.write(reference, {"kind": "mock-reference-v1", "engineering_only": True,
                              "instances": [{"file": row["file"], "reference": 1.0} for row in source["instances"]]})
        doc["research"]["reference"] = str(reference)
        doc["research"]["runs"][0]["seed"] = 800
        doc["research"]["runs"][1]["seed"] = 801
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


if __name__ == "__main__":
    with (tempfile.TemporaryDirectory() as directory,
          patch.object(socket.socket, "connect", deny), patch.object(socket, "create_connection", deny),
          patch.object(JsonCandidateTransport, "__init__", deny), patch.object(cli.subprocess, "run", deny),
          patch.object(problems, "solve_row", deny), patch.object(evaluation, "evaluate", deny),
          patch.object(execution, "sys", SimpleNamespace(platform="linux"))):
        report = {kind: run_case(kind, Path(directory)) for kind in ("automatic", "operator", "budget")}
        print(json.dumps({**report, "real_api": 0, "real_solves": 0, "slurm_submissions": 0}, indent=2))
