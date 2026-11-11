#!/usr/bin/env bash
#SBATCH --job-name=hdl-api-v5
#SBATCH --partition=128C_02
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:15:00
#SBATCH --signal=B:USR1@330
#SBATCH --output=logs/api-v5-%j.out
#SBATCH --error=logs/api-v5-%j.err
set -uo pipefail
set +x
cd /public2/home/qiuqian/hdl-deploy/api-common-v5-20261111 || exit 2
HDL_PY=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH
hdl_stop() { "$HDL_PY" -B tools/api_reliability_next.py stop --site cluster; }
trap hdl_stop USR1 TERM INT
HDL_ACTION=${1:-run}
case "$HDL_ACTION" in run|resume) ;; *) exit 2;; esac
srun "$HDL_PY" -u -B tools/api_reliability_next.py "$HDL_ACTION" --site cluster --allow-api --approve-total 4 \
 --mac-export deploy/api-common/mac-export.json --credential-file /public2/home/qiuqian/.config/hdl/leafapi.key &
HDL_STEP=$!
while true; do wait "$HDL_STEP"; HDL_RC=$?; if ! kill -0 "$HDL_STEP" 2>/dev/null; then break; fi; done
exit "$HDL_RC"
