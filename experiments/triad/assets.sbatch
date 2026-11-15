#!/usr/bin/env bash
set -euo pipefail
set +x
HDL_ASSET=${1:?};HDL_PY=${2:?}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 SLURM_EXPORT_ENV=ALL
unset PYTHONPATH LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
if [[ $HDL_ASSET == lkh ]]; then
  srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:?}" "$HDL_PY" -s -u -B experiments/triad/assets.py lkh-run --run-dir "${3:?}" --allow-lkh --approve-lkh "${4:?}"
else
  HDL_ACTION=${3:?};HDL_CONFIG=${4:?};HDL_RUN=${5:?};HDL_CAP=${6:?}
  hdl_pause() { "$HDL_PY" -s -B experiments/triad/entry.py pause --kind h-build --config "$HDL_CONFIG" --run-dir "$HDL_RUN" || true; }
  trap hdl_pause USR1 TERM INT
  srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:?}" "$HDL_PY" -s -u -B experiments/triad/entry.py "$HDL_ACTION" --kind h-build --config "$HDL_CONFIG" --run-dir "$HDL_RUN" --allow-api --allow-solves --approve-budget "$HDL_CAP" &
  HDL_PID=$!
  while true; do
    set +e
    wait "$HDL_PID";HDL_RC=$?
    set -e
    if ! kill -0 "$HDL_PID" 2>/dev/null; then break; fi
  done
  exit "$HDL_RC"
fi
