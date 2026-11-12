#!/usr/bin/env bash
#SBATCH --job-name=hdl-flow-A
#SBATCH --partition=128C_02
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:15:00
#SBATCH --no-requeue
#SBATCH --signal=B:USR1@120
#SBATCH --output=logs/flow-%j.out
#SBATCH --error=logs/flow-%j.err
set -uo pipefail
set +x
cd /public2/home/qiuqian/hdl-deploy/fjsp-state-a-flow-20261112 || exit 2
HDL_PY=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH LEAFAPI_API_KEY
hdl_stop() { "$HDL_PY" -B tools/flow_check.py stop --site cluster; }
trap hdl_stop USR1 TERM INT
HDL_ACTION=${1:?run or resume required};HDL_EXPORT=${2:?Mac export required}
case "$HDL_ACTION" in run|resume) ;; *) exit 2;; esac
srun "$HDL_PY" -u -B tools/flow_check.py "$HDL_ACTION" --site cluster --allow-evaluation --approve-solves 12 --mac-export "$HDL_EXPORT" &
HDL_STEP=$!
while true; do wait "$HDL_STEP"; HDL_RC=$?; if ! kill -0 "$HDL_STEP" 2>/dev/null; then break; fi; done
exit "$HDL_RC"
