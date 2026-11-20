#!/usr/bin/env bash
set -euo pipefail
set +x

HDL_ROOT=$(pwd -P)
HDL_PY=${1:?absolute Python path required}
HDL_REPORT="$HDL_ROOT/reports/r15-fs-smoke/${SLURM_JOB_ID:?}"
mkdir -p "$(dirname "$HDL_REPORT")"
mkdir "$HDL_REPORT"
unset LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
export PYTHONPATH="$HDL_ROOT/code:$HDL_ROOT" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
srun --ntasks=2 --cpus-per-task=1 "$HDL_PY" -s -B -c '
import os, sys, time
from pathlib import Path
from experiments.triad.batch_admission import try_lock
from experiments.triad.concurrency_probe import claim, filesystem_check, wait_file

folder = Path(sys.argv[1])
role = int(os.environ["SLURM_PROCID"])
deadline = time.time() + 90
filesystem_check(folder, role, deadline)
lock = folder / "permit-test.lock"
if role == 0:
    with try_lock(lock) as owned:
        assert owned
        claim(folder / "permit-held.json", {"owner": 0})
        wait_file(folder / "permit-peer.json", deadline, folder)
    claim(folder / "permit-released.json", {"released": True})
else:
    wait_file(folder / "permit-held.json", deadline, folder)
    with try_lock(lock) as owned:
        assert not owned, "two Slurm nodes held the same permit"
    claim(folder / "permit-peer.json", {"observed_busy": True})
    wait_file(folder / "permit-released.json", deadline, folder)
    with try_lock(lock) as owned:
        assert owned, "permit could not be acquired after release"
claim(folder / f"permit-pass-{role}.json", {"role": role, "passed": True})
' "$HDL_REPORT"
printf 'Shared filesystem probe passed. Receipts in %s\n' "$HDL_REPORT"
