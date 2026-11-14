#!/usr/bin/env bash
set -euo pipefail
set +x
HDL_PROBE_DIR=${1:?};HDL_ROLE=${2:?};HDL_PY=${3:?}
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY PYTHONPATH
exec srun --ntasks=1 --cpus-per-task=1 "$HDL_PY" -s -u -B experiments/triad/concurrency_probe.py worker --directory "$HDL_PROBE_DIR" --role "$HDL_ROLE" --approve-sends 4
