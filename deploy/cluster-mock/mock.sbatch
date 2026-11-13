#!/usr/bin/env bash
#SBATCH --job-name=fjsp-noapi-mock
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=3
#SBATCH --mem=1G
#SBATCH --time=00:10:00
#SBATCH --signal=B:USR1@120
#SBATCH --no-requeue
set -euo pipefail
set +x
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 SLURM_EXPORT_ENV=ALL
unset PYTHONPATH LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY HDL_LOCAL_OFFLINE_ACCEPTANCE
HDL_PY=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
HDL_ROOT=$(pwd -P)
HDL_OUTPUT="$HDL_ROOT/acceptance/job-${SLURM_JOB_ID:?}"
hdl_stop() { if [ -n "${HDL_STEP_PID:-}" ]; then kill -TERM "$HDL_STEP_PID" 2>/dev/null || true; fi; }
trap hdl_stop USR1 TERM INT
srun --ntasks=1 --cpus-per-task=3 "$HDL_PY" -u -B deploy/cluster-mock/accept.py run --output "$HDL_OUTPUT" &
HDL_STEP_PID=$!
while true; do
  set +e
  wait "$HDL_STEP_PID"
  HDL_RC=$?
  set -e
  if ! kill -0 "$HDL_STEP_PID" 2>/dev/null; then break; fi
done
exit "$HDL_RC"
