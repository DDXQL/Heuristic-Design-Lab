#!/usr/bin/env bash
set -euo pipefail
set +x
HDL_ACTION=${1:?}; HDL_CONFIG=${2:?}; HDL_RUN=${3:?}; HDL_PY=${4:?}; HDL_CAP=${5:?}
HDL_PREFIX=${6:-}; HDL_SOLVES=${7:-}; HDL_SHARED=${8:?}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 SLURM_EXPORT_ENV=ALL
unset PYTHONPATH LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
HDL_ARGS=(--config "$HDL_CONFIG" --run-dir "$HDL_RUN" --shared-manifest "$HDL_SHARED")
HDL_MODE=$("$HDL_PY" -s -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["mode"])' "$HDL_CONFIG")
if [[ $HDL_MODE == mock ]]; then HDL_ARGS+=(--engineering); else HDL_ARGS+=(--allow-api --allow-solves --approve-budget "$HDL_CAP"); fi
if [[ -n $HDL_PREFIX ]]; then HDL_ARGS+=(--pause-after-attempts "$HDL_PREFIX" --approve-segment-solves "$HDL_SOLVES"); fi
hdl_pause() { "$HDL_PY" -s -B experiments/triad/entry.py pause --config "$HDL_CONFIG" --run-dir "$HDL_RUN" --shared-manifest "$HDL_SHARED" || true; }
trap hdl_pause USR1 TERM INT
srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:?}" "$HDL_PY" -s -u -B experiments/triad/entry.py "$HDL_ACTION" "${HDL_ARGS[@]}" &
HDL_PID=$!
while true; do
  set +e
  wait "$HDL_PID"; HDL_RC=$?
  set -e
  if ! kill -0 "$HDL_PID" 2>/dev/null; then break; fi
done
exit "$HDL_RC"
