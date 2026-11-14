#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --no-requeue
set -euo pipefail
set +x
HDL_ACTION=${1:?};HDL_CONFIG=${2:?};HDL_RUN=${3:?};HDL_PY=${4:?};HDL_CAP=${5:?}
HDL_BOUNDARY_ARGS=(--allow-api --allow-solves --approve-budget "$HDL_CAP")
if [[ -n ${6:-} ]]; then HDL_BOUNDARY_ARGS+=(--pause-after-attempts "$6" --approve-segment-solves "${7:?}"); fi
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 SLURM_EXPORT_ENV=ALL
unset PYTHONPATH LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
hdl_pause() { "$HDL_PY" -s -B experiments/triad/entry.py pause --config "$HDL_CONFIG" --run-dir "$HDL_RUN" || true; }
trap hdl_pause USR1 TERM INT
srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:?}" "$HDL_PY" -s -u -B experiments/triad/entry.py "$HDL_ACTION" --config "$HDL_CONFIG" --run-dir "$HDL_RUN" "${HDL_BOUNDARY_ARGS[@]}" &
HDL_STEP_PID=$!
while true; do
  set +e
  wait "$HDL_STEP_PID";HDL_RC=$?
  set -e
  if ! kill -0 "$HDL_STEP_PID" 2>/dev/null; then break; fi
done
exit "$HDL_RC"
