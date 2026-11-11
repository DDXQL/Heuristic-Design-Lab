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
HDL_STATE="$HOME/hdl-api-validation/mac-cluster-api-v5-20261111/mac"
if [ -e "$HDL_STATE/claim.json" ] || [ -e "$HDL_STATE/ledger.json" ] || [ -e "$HDL_STATE/export.json" ]; then
  printf '%s\n' 'Mac阶段已有记录；请查看status并按原账本接续，不重新run。' >&2; exit 2
fi
# Terminal input only. Never inspect credential files or persist/echo the value.
hdl_credential_present() {
  case "${LEAFAPI_API_KEY:-}" in ''|*[[:space:]]*) return 1;; esac
}
if ! hdl_credential_present; then
  if [ ! -t 0 ]; then
    printf '%s\n' 'Mac凭据缺少或包含空白；请在交互终端启动，或预先设置LEAFAPI_API_KEY。尚未连接SSH或预留请求。' >&2; exit 2
  fi
  printf '%s' 'LeafAPI密钥（隐藏输入，仅供本次进程使用）：' > /dev/tty
  if ! IFS= read -r -s LEAFAPI_API_KEY < /dev/tty; then
    printf '\n%s\n' '未读到凭据；停止，未预留请求。' > /dev/tty; exit 2
  fi
  printf '\n' > /dev/tty
fi
if ! hdl_credential_present; then
  printf '%s\n' '凭据为空或包含空白；停止，未连接SSH或预留请求。' >&2; exit 2
fi
# Expose the value only to the explicitly authorized Mac API process, not SSH.
export -n LEAFAPI_API_KEY
HDL_LAUNCH_DIR="reports/api-common-20261111/launch-$(date +%Y%m%d-%H%M%S)-$$"
mkdir "$HDL_LAUNCH_DIR"
HDL_REMOTE=qiuqian@110.1.2.1
HDL_SHARED_CONTROL=$(mktemp -d /tmp/hdl-api.XXXXXX)
export HDL_SHARED_CONTROL
HDL_SSH_OPTS=(-o ControlMaster=auto -o ControlPersist=1200 -o "ControlPath=$HDL_SHARED_CONTROL/%C" -o ProxyJump=custom@222.201.144.188:22)
hdl_disconnect() { ssh "${HDL_SSH_OPTS[@]}" -O exit "$HDL_REMOTE" >/dev/null 2>&1 || true; rmdir "$HDL_SHARED_CONTROL" 2>/dev/null || true; }
trap hdl_disconnect EXIT
exec > >(tee -a reports/api-common-20261111/user-launch.log) 2>&1
printf '本次启动材料：%s/%s\n' "$HDL_ROOT" "$HDL_LAUNCH_DIR"
"$HDL_PY" -B tools/api_reliability_next.py check-only
"$HDL_PY" -B tools/api_reliability_next.py replay > "$HDL_LAUNCH_DIR/replay.json"
# Pure file/Slurm inventory on login node; no project imports or model requests.
# It runs before Mac requests and refuses active/queued jobs or uncertain scheduler status.
ssh "${HDL_SSH_OPTS[@]}" "$HDL_REMOTE" '/public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B - --require-idle' \
 < deploy/api-common/inspect_remote.py > "$HDL_LAUNCH_DIR/remote-before.json"
HDL_RC=0
LEAFAPI_API_KEY="$LEAFAPI_API_KEY" caffeinate -i "$HDL_PY" -u -B tools/api_reliability_next.py run --site mac --allow-api --approve-total 4 || HDL_RC=$?
unset LEAFAPI_API_KEY
if [ ! -f "$HDL_STATE/export.json" ]; then
  printf '%s\n' 'Mac阶段未生成结果导出；停止，不传输或提交集群诊断。保留已有状态，不补发请求。' >&2
  if [ "$HDL_RC" -ne 0 ]; then exit "$HDL_RC"; else exit 2; fi
fi
# A refused, paused or unknown Mac receipt is rejected before the cluster can be submitted.
bash deploy/api-common/submit_cluster.sh run --approve-total 4
