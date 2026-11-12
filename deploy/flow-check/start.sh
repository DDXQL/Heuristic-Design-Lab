#!/usr/bin/env bash
# Explicit user start only: new API2 + total solve12, never old diagnosis budget.
set -euo pipefail
set +x
HDL_ACTION=run
if [ "${1:-}" = --resume ]; then HDL_ACTION=resume; shift; fi
if [ "$#" -ne 6 ] || [ "$1" != --allow-api ] || [ "$2" != --approve-api ] || [ "$3" != 2 ] || [ "$4" != --allow-evaluation ] || [ "$5" != --approve-solves ] || [ "$6" != 12 ]; then
  printf '%s\n' 'Usage: start.sh [--resume] --allow-api --approve-api 2 --allow-evaluation --approve-solves 12' >&2; exit 2
fi
HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HDL_PY=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python
HDL_STATE="$HOME/hdl-flow-validation/fjsp-state-a-flow-20261112/mac"
cd "$HDL_ROOT"
export -n LEAFAPI_API_KEY
if [ "$HDL_ACTION" = run ] && [ -e "$HDL_STATE" ]; then printf '%s\n' 'Existing Mac flow: use status/resume or submit_cluster.sh; never reset or rerun.' >&2; exit 2; fi
if [ "$HDL_ACTION" = resume ]; then
  "$HDL_PY" -B -c 'import json,sys; s=json.load(open(sys.argv[1])); assert s["phase"]=="paused", "resume requires safely paused phase"' "$HDL_STATE/checkpoint.json"
fi
hdl_key_present() { case "${LEAFAPI_API_KEY:-}" in ''|*[[:space:]]*) return 1;; esac; }
if ! hdl_key_present; then
  if [ ! -t 0 ]; then printf '%s\n' 'Use an interactive terminal for hidden LeafAPI input; no stage claimed.' >&2; exit 2; fi
  printf '%s' 'LeafAPI密钥（隐藏输入，仅供Mac本次请求）：' >/dev/tty
  IFS= read -r -s LEAFAPI_API_KEY </dev/tty || exit 2
  printf '\n' >/dev/tty
fi
if ! hdl_key_present; then printf '%s\n' 'Empty/malformed key; no stage claimed.' >&2; exit 2; fi
export -n LEAFAPI_API_KEY
HDL_SHARED_CONTROL=$(mktemp -d /tmp/hdl-flow.XXXXXX);export HDL_SHARED_CONTROL
HDL_REMOTE=qiuqian@110.1.2.1
HDL_SSH=(-o ControlMaster=auto -o ControlPersist=1800 -o "ControlPath=$HDL_SHARED_CONTROL/%C" -o ProxyJump=custom@222.201.144.188:22)
hdl_cleanup() { ssh "${HDL_SSH[@]}" -O exit "$HDL_REMOTE" >/dev/null 2>&1 || true; rmdir "$HDL_SHARED_CONTROL" 2>/dev/null || true; }
trap hdl_cleanup EXIT
HDL_RUN_LOG="reports/flow-check-20261112/launch-$(date +%Y%m%d-%H%M%S)-$$";mkdir "$HDL_RUN_LOG"
exec > >(tee -a "$HDL_RUN_LOG/user-launch.log") 2>&1
printf '本次启动记录：%s/%s\n' "$HDL_ROOT" "$HDL_RUN_LOG"
"$HDL_PY" -B tools/flow_check.py check-only
"$HDL_PY" -B tools/flow_check.py bundle
HDL_ZIP=/Users/DDXQL/Developer/transfer-outbox/fjsp-state-a-flow-20261112.zip
HDL_HASH=$(shasum -a 256 "$HDL_ZIP" | cut -d' ' -f1)
HDL_UPLOAD="flow-upload-$(date +%Y%m%d-%H%M%S)-$$.zip"
HDL_STAGING="fjsp-state-a-flow-staging-$(date +%Y%m%d-%H%M%S)-$$"
scp "${HDL_SSH[@]}" "$HDL_ZIP" "$HDL_REMOTE:/public2/home/qiuqian/hdl-deploy/$HDL_UPLOAD"
# Verify compute dependencies and idle personal queue BEFORE any Mac solve/API.
ssh "${HDL_SSH[@]}" "$HDL_REMOTE" "set -e; cd /public2/home/qiuqian/hdl-deploy; printf '%s  %s\\n' '$HDL_HASH' '$HDL_UPLOAD' | sha256sum -c -; if [ ! -e fjsp-state-a-flow-20261112 ]; then mkdir '$HDL_STAGING'; /public2/home/qiuqian/hdl-envs/portable-v2/bin/python -m zipfile -e '$HDL_UPLOAD' '$HDL_STAGING'; mv -T -n '$HDL_STAGING' fjsp-state-a-flow-20261112; fi; cd fjsp-state-a-flow-20261112; /public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B tools/flow_check.py check-only; HDL_QUEUE=\$(squeue -u qiuqian -h); printf '%s\\n' \"\$HDL_QUEUE\"; if [ -n \"\$HDL_QUEUE\" ]; then printf '%s\\n' 'Existing personal jobs: stop before Mac requests/evaluation; no automatic cancellation.' >&2; exit 3; fi" > "$HDL_RUN_LOG/remote-before.log"
LEAFAPI_API_KEY="$LEAFAPI_API_KEY" caffeinate -i "$HDL_PY" -u -B tools/flow_check.py "$HDL_ACTION" --site mac --allow-api --approve-api 2 --allow-evaluation --approve-solves 12
unset LEAFAPI_API_KEY
"$HDL_PY" -B tools/flow_check.py check-mac-export --mac-export "$HDL_STATE/export.json"
bash deploy/flow-check/submit_cluster.sh run --allow-evaluation --approve-solves 12
