#!/usr/bin/env bash
# User-invoked from an existing cluster login. Never run by the assistant.
set -euo pipefail
if [[ "$*" != '--submit --allow-api --allow-solves --approve-requests 2040 --approve-new-requests 2 --approve-new-solves 84 --acknowledge-known-failures-keep-budget' ]]; then
  printf '%s\n' 'Explicit original2040 + new2 requests/84 inclusive solves + failure acknowledgment required' >&2
  exit 2
fi
HDL_RECOVERY_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$HDL_RECOVERY_ROOT"
HDL_RECOVERY_PY=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
"$HDL_RECOVERY_PY" -s -B experiments/triad/stop_recovery.py activate --acknowledge-known-failures-keep-budget
"$HDL_RECOVERY_PY" -s -B experiments/triad/stop_recovery.py finite-submit --submit --allow-api --allow-solves --approve-requests 2040 --approve-new-requests 2 --approve-new-solves 84
