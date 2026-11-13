#!/usr/bin/env bash
#SBATCH --job-name=fjsp-solve16
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=3
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --signal=B:USR1@120
#SBATCH --no-requeue
set -euo pipefail
set +x
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 SLURM_EXPORT_ENV=ALL
unset PYTHONPATH LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
HDL_PY=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
hdl_stop() { if [ -n "${HDL_STEP_PID:-}" ]; then kill -TERM "$HDL_STEP_PID" 2>/dev/null || true; fi; }
trap hdl_stop USR1 TERM INT
srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:?}" "$HDL_PY" -u -B deploy/solve-check/accept.py run --allow-solves --approve-solves 16 &
HDL_STEP_PID=$!
while true; do
  set +e
  wait "$HDL_STEP_PID";HDL_RC=$?
  set -e
  if ! kill -0 "$HDL_STEP_PID" 2>/dev/null; then break; fi
done
exit "$HDL_RC"
