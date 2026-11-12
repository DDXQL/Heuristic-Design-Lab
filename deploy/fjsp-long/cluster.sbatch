#!/usr/bin/env bash
# Resource arguments come from submit.py and the frozen deployment JSON.
#SBATCH --job-name=fjsp-U-long
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --no-requeue
set -euo pipefail
set +x
HDL_ACTION=${1:?run or resume}
HDL_CONFIG=${2:?absolute frozen configuration path}
HDL_PY=${3:?existing cluster Python}
HDL_CREDENTIAL=${4:?existing mode600 credential path}
HDL_PREFIX=${5:-}
if [ -n "$HDL_PREFIX" ]; then
  case "$HDL_PREFIX" in *[!0-9]*) exit 2;; esac
fi
case "$HDL_ACTION" in run|resume) ;; *) exit 2;; esac
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH LEAFAPI_API_KEY
HDL_ROOT=$(pwd -P)
cd "$HDL_ROOT"
# The Python entry reads the existing owner-only file only after launch gates.
hdl_pause() {
  "$HDL_PY" -B experiments/common/run_frozen.py pause --config "$HDL_CONFIG"
}
trap hdl_pause USR1 TERM INT
HDL_COMMAND=("$HDL_PY" -u -B experiments/common/run_frozen.py "$HDL_ACTION"
  --config "$HDL_CONFIG" --allow-api --allow-evaluation --credential-file "$HDL_CREDENTIAL")
if [ -n "$HDL_PREFIX" ]; then HDL_COMMAND+=(--pause-after-attempts "$HDL_PREFIX"); fi
srun --ntasks=1 "${HDL_COMMAND[@]}" &
HDL_STEP_PID=$!
HDL_EXIT=0
while true; do
  set +e
  wait "$HDL_STEP_PID"
  HDL_EXIT=$?
  set -e
  if ! kill -0 "$HDL_STEP_PID" 2>/dev/null; then break; fi
done
exit "$HDL_EXIT"
