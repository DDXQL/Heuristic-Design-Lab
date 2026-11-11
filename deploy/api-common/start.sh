#!/usr/bin/env bash
# Explicit user launch: two bounded Mac slots, then a separately scheduled cluster stage.
set -euo pipefail
set +x
if [ "$#" -ne 3 ] || [ "$1" != --allow-api ] || [ "$2" != --approve-total ] || [ "$3" != 4 ]; then
  printf '%s\n' 'Usage: bash deploy/api-common/start.sh --allow-api --approve-total 4' >&2; exit 2
fi
HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HDL_PY=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python
cd "$HDL_ROOT"
HDL_REMOTE=qiuqian@110.1.2.1
HDL_SHARED_CONTROL=$(mktemp -d /tmp/hdl-api.XXXXXX)
export HDL_SHARED_CONTROL
HDL_SSH_OPTS=(-o ControlMaster=auto -o ControlPersist=1200 -o "ControlPath=$HDL_SHARED_CONTROL/%C" -o ProxyJump=custom@222.201.144.188:22)
hdl_disconnect() { ssh "${HDL_SSH_OPTS[@]}" -O exit "$HDL_REMOTE" >/dev/null 2>&1 || true; rmdir "$HDL_SHARED_CONTROL" 2>/dev/null || true; }
trap hdl_disconnect EXIT
exec > >(tee -a reports/api-common-20261111/user-launch.log) 2>&1
"$HDL_PY" -B tools/api_reliability_next.py check-only
"$HDL_PY" -B tools/api_reliability_next.py replay > reports/api-common-20261111/user-replay.json
# Pure file/Slurm inventory on login node; no project imports or model requests.
# It runs before Mac requests and refuses active/queued jobs or uncertain scheduler status.
ssh "${HDL_SSH_OPTS[@]}" "$HDL_REMOTE" '/public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B - --require-idle' \
 < deploy/api-common/inspect_remote.py > reports/api-common-20261111/remote-before.json
HDL_RC=0
caffeinate -i "$HDL_PY" -u -B tools/api_reliability_next.py run --site mac --allow-api --approve-total 4 || HDL_RC=$?
# A refused, paused or unknown Mac receipt is rejected before the cluster can be submitted.
bash deploy/api-common/submit_cluster.sh run --approve-total 4
