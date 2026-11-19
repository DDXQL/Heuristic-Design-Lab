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
from experiments.triad.concurrency_probe import filesystem_check
filesystem_check(sys.argv[1], int(os.environ["SLURM_PROCID"]), time.time() + 90)
' "$HDL_REPORT"
printf 'Shared filesystem probe passed. Receipts in %s\n' "$HDL_REPORT"
