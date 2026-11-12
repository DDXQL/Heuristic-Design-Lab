#!/usr/bin/env bash
# Mac-only credential convenience; the frozen launcher still owns every gate.
set -euo pipefail
set +x
export -n LEAFAPI_API_KEY
export -n HDL_SAVED_KEY
HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HDL_SECURITY=/usr/bin/security
HDL_SERVICE=org.heuristic-design-lab.leafapi
HDL_ACCOUNT=LEAFAPI_API_KEY
hdl_clear() { unset LEAFAPI_API_KEY HDL_SAVED_KEY; }
trap hdl_clear EXIT
hdl_valid() { case "${1:-}" in ''|*[[:space:]]*) return 1;; esac; }
hdl_usage() {
  printf '%s\n' 'Usage: start-with-keychain.sh --setup-only | --check-only | [--resume] --allow-api --approve-api 2 --allow-evaluation --approve-solves 12' >&2
}
if [ "$#" = 0 ] || { [ "$#" = 1 ] && [ "$1" = --check-only ]; }; then
  printf '%s\n' 'offline=true model_requests=0 solves=0 keychain_reads=0; use --setup-only once, then pass the original explicit launch flags.'
  exit 0
fi
HDL_SETUP=false
if [ "$#" = 1 ] && [ "$1" = --setup-only ]; then
  HDL_SETUP=true
else
  HDL_ARGS=("$@")
  if [ "${1:-}" = --resume ]; then shift; fi
  if [ "$#" -ne 6 ] || [ "$1" != --allow-api ] || [ "$2" != --approve-api ] || [ "$3" != 2 ] || [ "$4" != --allow-evaluation ] || [ "$5" != --approve-solves ] || [ "$6" != 12 ]; then
    hdl_usage; exit 2
  fi
fi
if [ "$(/usr/bin/uname -s)" != Darwin ]; then
  printf '%s\n' 'This credential helper requires macOS; no model request or solve started.' >&2; exit 2
fi
if [ "$HDL_SETUP" = true ]; then
  if [ ! -t 0 ]; then printf '%s\n' 'Run --setup-only in an interactive terminal; no credential read or written.' >&2; exit 2; fi
  unset LEAFAPI_API_KEY
  printf '%s\n' '请在系统提示中隐藏输入LeafAPI密钥，保存到Mac钥匙串。本步骤不请求模型、不求解、不提交作业。'
  # -w MUST be last with no argument: security prompts itself. The secret never
  # enters shell history, argv, a temporary file, or this wrapper's log output.
  "$HDL_SECURITY" add-generic-password -U -a "$HDL_ACCOUNT" -s "$HDL_SERVICE" -l 'Heuristic-Design-Lab LeafAPI' -w
elif hdl_valid "${LEAFAPI_API_KEY:-}"; then
  # An explicitly supplied process credential remains an override; do not save it.
  LEAFAPI_API_KEY="$LEAFAPI_API_KEY" /bin/bash "$HDL_ROOT/deploy/flow-check/start.sh" "${HDL_ARGS[@]}"
  exit $?
elif [ -n "${LEAFAPI_API_KEY:-}" ]; then
  printf '%s\n' 'LEAFAPI_API_KEY contains whitespace; no model request or solve started.' >&2; exit 2
fi
if ! HDL_SAVED_KEY=$("$HDL_SECURITY" find-generic-password -a "$HDL_ACCOUNT" -s "$HDL_SERVICE" -w 2>/dev/null); then
  printf '%s\n' '钥匙串尚未设置或访问未获准。先运行本脚本 --setup-only；已设置时请解锁/允许钥匙串访问。未启动模型或求解。' >&2; exit 2
fi
if ! hdl_valid "$HDL_SAVED_KEY"; then
  printf '%s\n' '钥匙串中的密钥为空或含空白，请用 --setup-only 更新。未启动模型或求解。' >&2; exit 2
fi
if [ "$HDL_SETUP" = true ]; then
  printf '%s\n' '密钥已保存并检查格式；之后使用本脚本启动，无需再次输入API key。模型请求0、求解0、提交0。'
  exit 0
fi
LEAFAPI_API_KEY="$HDL_SAVED_KEY" /bin/bash "$HDL_ROOT/deploy/flow-check/start.sh" "${HDL_ARGS[@]}"
