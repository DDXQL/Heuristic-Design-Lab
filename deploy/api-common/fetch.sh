#!/usr/bin/env bash
# Copy diagnostic output and logs only; no remote export/replay/search or submission.
set -euo pipefail
set +x
HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HDL_LOCAL="$HDL_ROOT/reports/api-common-20261111/returned-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$HDL_LOCAL"
scp -r -o ProxyJump=custom@222.201.144.188:22 \
 qiuqian@110.1.2.1:/public2/home/qiuqian/hdl-api-validation/mac-cluster-api-v5-20261111/cluster \
 qiuqian@110.1.2.1:/public2/home/qiuqian/hdl-deploy/api-common-v5-20261111/logs "$HDL_LOCAL/"
printf '%s\n' "$HDL_LOCAL"
