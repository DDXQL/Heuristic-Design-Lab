#!/usr/bin/env bash
#SBATCH --job-name=fjsp-eoh-J
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --signal=B:USR1@120
#SBATCH --no-requeue
# CPU, memory, partition, account/QOS and time ONLY from the approved job.py plan.
set -euo pipefail
set +x
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 SLURM_EXPORT_ENV=ALL
unset PYTHONPATH LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY
HDL_PY=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
HDL_ACTION=${1:?job.py supplies run or resume}
HDL_CAP=${2:?job.py supplies original cumulative request cap}
HDL_RUN="$PWD/runs/fjsp-eoh-J-baseline-20261113-r1"
hdl_pause() { "$HDL_PY" -s -B experiments/common/run_fjsp_eoh_gap.py pause --run-dir "$HDL_RUN" || true; }
trap hdl_pause USR1 TERM INT
srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:?}" "$HDL_PY" -s -u -B experiments/common/run_fjsp_eoh_gap.py "$HDL_ACTION" --run-dir "$HDL_RUN" --allow-api --approve-budget "$HDL_CAP" &
HDL_STEP_PID=$!
while true; do
  set +e
  wait "$HDL_STEP_PID";HDL_RC=$?
  set -e
  if ! kill -0 "$HDL_STEP_PID" 2>/dev/null; then break; fi
done
exit "$HDL_RC"
