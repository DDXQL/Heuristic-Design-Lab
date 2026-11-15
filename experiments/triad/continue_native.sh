#!/usr/bin/env bash
# Explicit human invocation only. No retries, lease deletion or checkpoint edits.
set -euo pipefail
if [[ "$*" != '--submit --allow-api --allow-solves --approve-requests 2040' ]]; then
  printf '%s\n' 'Requires exactly: --submit --allow-api --allow-solves --approve-requests 2040' >&2
  exit 2
fi
HDL_NATIVE_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$HDL_NATIVE_ROOT"
HDL_NATIVE_PY=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
HDL_NATIVE_PARENT=/public2/home/qiuqian/hdl-deploy/triad-concurrent-prompt-v2-20261115-r8
"$HDL_NATIVE_PY" -s -B experiments/triad/native_continuation.py prepare
"$HDL_NATIVE_PY" -s -B "$HDL_NATIVE_PARENT/experiments/triad/parallel.py" close --manifest "$HDL_NATIVE_PARENT/plans/first-eoh-501-502/Shared.json"
"$HDL_NATIVE_PY" -s -B experiments/triad/native_continuation.py activate
"$HDL_NATIVE_PY" -s -B experiments/triad/parallel.py submit --manifest plans/native-eoh-501-502/Shared.json "$@"
