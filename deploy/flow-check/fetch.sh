#!/usr/bin/env bash
# Metadata / existing response and result collection only; no evaluation.
set -euo pipefail
unset LEAFAPI_API_KEY
HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd);cd "$HDL_ROOT"
HDL_JOB=${1:-}
if [ -z "$HDL_JOB" ] && [ -f reports/flow-check-20261112/submitted-jobs.txt ]; then HDL_JOB=$(tail -n 1 reports/flow-check-20261112/submitted-jobs.txt); fi
case "$HDL_JOB" in ''|*[!0-9]*) printf '%s\n' 'Provide this flow job ID.' >&2; exit 2;; esac
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/api_reliability_collect.py --job-id "$HDL_JOB" --flow-profile
