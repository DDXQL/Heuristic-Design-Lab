#!/usr/bin/env bash
set -euo pipefail
set +x
HDL_QUEUE=${1:?};HDL_OPERATION=${2:?};HDL_TOTAL=${3:?}
HDL_PY=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset LEAFAPI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY PYTHONPATH
hdl_pause() { "$HDL_PY" -s -B experiments/triad/serial_queue.py pause --queue "$HDL_QUEUE" || true; }
trap hdl_pause USR1 TERM INT
srun --ntasks=1 --cpus-per-task=4 "$HDL_PY" -s -u -B experiments/triad/serial_queue.py "$HDL_OPERATION" --queue "$HDL_QUEUE" --approve-total "$HDL_TOTAL" &
HDL_PID=$!
while true; do
  set +e
  wait "$HDL_PID"; HDL_RC=$?
  set -e
  if ! kill -0 "$HDL_PID" 2>/dev/null; then break; fi
done
exit "$HDL_RC"
