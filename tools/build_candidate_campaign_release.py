#!/usr/bin/env python3
"""Build the new campaign package from Git and the verified frozen R13 asset archive."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / "transfer-outbox"
BASE = OUT / "triad-tsp-lkh-candidate-20261117-r13.zip"
VERSION = "triad-candidate-runtime-20261119-r15"
ENTRY = "docs/长实验自动续跑与结果导出.md"
PREFIXES = ("code/", "experiments/triad/", "configurations/six-groups-20261116/", "docs/")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def build(base, target):
    sidecar = target.with_suffix(".zip.sha256")
    if target.exists() or sidecar.exists():
        raise FileExistsError("existing release or checksum; choose a new output path")
    if sha(base.read_bytes()) != base.with_suffix(".zip.sha256").read_text().split()[0]:
        raise ValueError("R13 input archive checksum mismatch")
    with zipfile.ZipFile(base) as archive:
        old = json.loads(archive.read("release.json"))
        if old["version"] != "triad-tsp-lkh-candidate-20261117-r13":
            raise ValueError("unexpected base release")
        payload = {
            name: archive.read(name) for name in old["files"]
            if not name.startswith("preparations/operations/lkh-candidate-3.0.13/")
        }
    if any(sha(raw) != old["files"][name] for name, raw in payload.items()):
        raise ValueError("base member checksum mismatch")
    commit = git("rev-parse", "HEAD").decode().strip()
    changed = git("diff", "--name-only", "-z", "--diff-filter=AM", old["engineering_commit"], commit)
    for raw in changed.split(b"\0"):
        if not raw:
            continue
        name = raw.decode()
        if name in ("README.md", "AGENTS.md") or name.startswith(PREFIXES):
            payload[name] = git("show", f"{commit}:{name}")
    required = {ENTRY, "experiments/triad/campaign.py", "experiments/triad/candidate_policy.py",
                "configurations/six-groups-20261116/candidate-policy.draft.json"}
    if not required.issubset(payload):
        raise ValueError("commit the complete campaign implementation before packaging")
    if any(Path(n).is_absolute() or ".." in Path(n).parts or n.startswith(("runs/", "logs/", ".venv/"))
           or Path(n).suffix in (".key", ".pem") or Path(n).name in
           ("generation.lock", "API_attempts.json", "checkpoint.json", "STOP.json") for n in payload):
        raise ValueError("unsafe file in release")
    release = {"version": VERSION, "engineering_commit": commit, "parent_commit": old["engineering_commit"],
               "entry": ENTRY, "API_execution_authorized": False, "deployed": False,
               "actual_TSP_reference_included": False, "existing_runs_included": False,
               "files": {n: sha(raw) for n, raw in payload.items()}}
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in payload.items():
            archive.writestr(name, raw)
        archive.writestr("release.json", json.dumps(release, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(target) as archive:
        if any(sha(archive.read(n)) != h for n, h in release["files"].items()):
            raise ValueError("output release member verification failed")
    checksum = sha(target.read_bytes())
    with sidecar.open("x") as file:
        file.write(f"{checksum}  {target.name}\n")
    return {"archive": str(target), "sha256": checksum, "files": len(payload), "commit": commit,
            "deployed": False, "API_requests": 0, "Slurm_submissions": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--output", type=Path, default=OUT / (VERSION + ".zip"))
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.output), ensure_ascii=False, indent=2))
