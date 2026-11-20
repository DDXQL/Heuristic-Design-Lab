#!/usr/bin/env python3
"""Stage and verify the R15p4 release, or run its no-API Slurm acceptance."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


SOURCE = Path(__file__).resolve().parent
COMMIT = "721e9ed4f07a763b1c226fee362cad67d0fa5846"
RELEASE = "triad-candidate-runtime-20261120-r15p4-offline"
ROOT = Path.home() / "hdl-deploy" / "triad-candidate-runtime-20261120-r15p4"
SITE = "r15p4-site-no-api"
SMOKE = Path("configurations/experiments") / (SITE + ".json")
TSP = Path("configurations/experiments/tsp-502-site-d06.json")
REFERENCE = Path("preparations/operations/tsp-reference-r15.json")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_bytes()) if path.is_file() else {}


def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True, timeout=90)


def stage():
    for line in (SOURCE / "SHA256SUMS").read_text().splitlines():
        digest, filename = line.split("  ", 1)
        need(sha((SOURCE / filename).read_bytes()) == digest, f"bundle hash differs: {filename}")
    with zipfile.ZipFile(SOURCE / "runtime.zip") as package:
        manifest_bytes = package.read("release.json")
        manifest = json.loads(manifest_bytes)
        need(manifest["engineering_commit"] == COMMIT and manifest["version"] == RELEASE, "wrong R15p4 release")
        names = manifest["files"]
        need(len(package.namelist()) == len(names) + 1 and set(package.namelist()) == {*names, "release.json"},
             "unexpected archive paths")
        for name, digest in names.items():
            path = Path(name)
            need(not path.is_absolute() and ".." not in path.parts and sha(package.read(name)) == digest,
                 f"invalid release member: {name}")
        if not ROOT.exists():
            ROOT.mkdir(parents=True)
            package.extractall(ROOT)
        need(not ROOT.is_symlink() and (ROOT / "release.json").read_bytes() == manifest_bytes,
             "existing deployment differs")
        for name, digest in names.items():
            need(sha((ROOT / name).read_bytes()) == digest, f"deployed release member differs: {name}")
    for path in (SMOKE, TSP, REFERENCE):
        data = (SOURCE / path.name).read_bytes()
        dst = ROOT / path
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            with dst.open("xb") as file:
                file.write(data)
        need(not dst.is_symlink() and dst.read_bytes() == data, f"site file differs: {path}")
    mock = json.loads(run(sys.executable, "-s", "-B", "tools/experiment.py", "prepare", str(SMOKE)))
    tsp = json.loads(run(sys.executable, "-s", "-B", "tools/experiment.py", "prepare", str(TSP)))
    config = read(ROOT / SMOKE)
    target = config["research"]["budget"]["target"]
    wall = config["execution"]["slurm"]["wall_seconds"]
    interval = config["execution"]["api"]["min_interval_seconds"]
    need(mock["ready_for_submission_checks"] and mock["mode"] == "mock" and mock["global_API_width"] == 8
         and mock["effective_max_requests"] == 3 and {r["seed"] for r in mock["members"]} == {901, 902, 903}
         and all(0 < wall - r["drain_seconds"] < (target - 1) * interval for r in mock["members"]),
         "three-seed Mock or segment timing preflight failed")
    need(tsp["ready_for_submission_checks"] and tsp["mode"] == "real", "TSP D06 asset preflight failed")
    return {"commit": COMMIT, "deployment": str(ROOT), "site": SITE, "mock": mock,
            "tsp_preflight_ready": True, "real_api_calls": 0, "actual_solves": 0}


def submit():
    for command in ("sbatch", "srun", "sacct", "squeue", "scontrol"):
        need(shutil.which(command), f"missing Slurm command: {command}")
    preflight = stage()
    report = ROOT / "reports" / SITE
    report.mkdir(parents=True, exist_ok=False)
    (report / "preflight.json").write_text(json.dumps(preflight, indent=2))
    fs = run("sbatch", "--parsable", "--no-requeue", "--partition=128C_02", "--account=wz", "--qos=normal",
             "--nodes=2", "--ntasks=2", "--ntasks-per-node=1", "--cpus-per-task=1", "--mem=1024M",
             "--time=00:05:00", "--job-name=r15p4-site-fs", "--output=" + str(report / "fs-%j.out"),
             "--error=" + str(report / "fs-%j.err"), "tools/experiment_fs_probe.sbatch", sys.executable)
    job = fs.strip().split(";")[0]
    need(job.isdigit(), "ambiguous filesystem job submission; inspect Slurm before any repeat")
    (report / "fs-job").write_text(job + "\n")
    result = json.loads(run(sys.executable, "-s", "-B", "tools/experiment.py", "run", str(SMOKE), "--approve"))
    (report / "mock-submission.json").write_text(json.dumps(result, indent=2))
    return {"filesystem_job": job, "mock_submission": result, "real_api_calls": 0, "actual_solves": 0}


def status():
    report = ROOT / "reports" / SITE
    plan = ROOT / "plans" / ("candidate-lab-" + SITE)
    m = read(plan / "Shared.json")
    result = read(plan / "Campaign_result.json")
    target = read(ROOT / SMOKE).get("research", {}).get("budget", {}).get("target")
    job_file = report / "fs-job"
    fs = job_file.read_text().strip() if job_file.is_file() else None
    peers = ROOT / "reports/r15-fs-smoke" / (fs or "not-submitted")
    hosts = [read(peers / f"fs-pass-{i}.json").get("host") for i in (0, 1)]
    permits = [read(peers / f"permit-pass-{i}.json").get("passed") is True for i in (0, 1)]
    reviews = [read(path) for path in sorted((plan / "campaign-control").glob("review-*.json"))]
    counts = []
    for row in m.get("members", []):
        d = Path(row["run_dir"])
        records = [read(path) for path in sorted((d / "submissions").glob("shared-*.json"))]
        cp = read(d / "checkpoint.json")
        summary = read(d / "exports/summary.json")
        ends = [read(path) for path in sorted((d / "end_receipts").glob("*.json"))]
        counts.append({"run_id": row["run_id"], "seed": row["seed"], "run_dir": str(d),
                       "phase": cp.get("phase"), "successful_evolution": cp.get("successful_evolution_responses"),
                       "confirmed_real_sends": summary.get("confirmed_sends"),
                       "mock_dispatches": summary.get("physical_sends_confirmed"),
                       "actual_solve_starts": sum(v["started"] for v in summary["physical_passes"].values())
                       if "physical_passes" in summary else None,
                       "engineering_only": summary.get("engineering_only"),
                       "ready_export": bool(summary) and summary["cursor"] == cp.get("cursor"),
                       "time_pause": any(e["phase"] == "paused" for e in ends) and len(records) > 1,
                       "jobs": [r.get("job_id") for r in records]})
    ids = list(dict.fromkeys(job for job in [fs, *(r.get("job_id") for r in reviews),
                                             *(j for row in counts for j in row["jobs"])] if job and job.isdigit()))
    ac = {}
    if ids:
        for line in run("sacct", "-n", "-P", "-X", "-j", ",".join(ids), "--format=JobIDRaw,State,ExitCode").splitlines():
            job, state, rc = line.split("|")
            if job in ids:
                ac[job] = [state, rc]
    complete = ["COMPLETED", "0:0"]
    filesystem = bool(all(hosts) and len(set(hosts)) == 2 and all(permits) and ac.get(fs) == complete)
    worker_jobs = [j for row in counts for j in row["jobs"]]
    dependencies = bool(len(reviews) >= 2 and all(ac.get(r.get("job_id")) == complete and r["workers"]
                         and all(j in worker_jobs and ac.get(j) == complete for j in r["workers"])
                         and "--dependency=afterany:" + ":".join(r["workers"]) in r["command"] for r in reviews)
                        and {j for r in reviews for j in r["workers"]} == set(worker_jobs))
    independent = len({row["run_dir"] for row in counts}) == 3 and {row["seed"] for row in counts} == {901, 902, 903}
    segmented = bool(m.get("mode") == "mock" and result.get("reason") == "scientific_complete"
                     and result.get("segments", 0) >= 2 and independent and len(set(worker_jobs)) == len(worker_jobs)
                     and all(row["phase"] == "completed" and row["successful_evolution"] == target
                             and row["ready_export"] and row["engineering_only"] is True
                             and row["confirmed_real_sends"] == row["actual_solve_starts"] == 0 for row in counts)
                     and any(row["time_pause"] for row in counts))
    return {"site_ready": filesystem and dependencies and segmented, "two_node_permits_ok": filesystem,
            "dependency_and_reviews_ok": dependencies, "three_seed_mock_ok": segmented, "hosts": hosts,
            "members": counts, "outcome": result.get("reason"), "slurm_jobs": ac,
            "review_errors": [read(p) for p in (plan / "campaign-control").glob("error-*.json")]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("check", "submit", "status"))
    cli.add_argument("--approve-mock", action="store_true")
    args = cli.parse_args()
    need(args.approve_mock == (args.action == "submit"), "submit requires --approve-mock")
    action = {"check": stage, "submit": submit, "status": status}[args.action]
    print(json.dumps(action(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
