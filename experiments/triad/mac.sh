#!/usr/bin/env bash
set -euo pipefail
set +x
HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd -P)
HDL_PY=${HDL_TRIAD_PYTHON:-/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python}
exec "$HDL_PY" -s -B "$HDL_ROOT/experiments/triad/batch.py" "$@"
