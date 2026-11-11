#!/usr/bin/env bash
# User-run transfer/submission only; never re-executes the Mac model phase.
set -euo pipefail
set +x
HDL_ACTION=${1:-}
case "$HDL_ACTION" in run|resume) ;; *) printf '%s\n' 'Usage: submit_cluster.sh run|resume --approve-total 4' >&2; exit 2;; esac
if [ "$#" -ne 3 ] || [ "$2" != --approve-total ] || [ "$3" != 4 ]; then exit 2; fi
HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HDL_PY=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python
HDL_MAC_EXPORT="$HOME/hdl-api-validation/mac-cluster-api-v5-20261111/mac/export.json"
if [ ! -f "$HDL_MAC_EXPORT" ]; then
  printf '%s\n' 'Mac阶段没有结果导出；不连接SSH、不传输、不提交集群诊断。请先检查Mac启动结果。' >&2; exit 2
fi
HDL_REMOTE=qiuqian@110.1.2.1
HDL_JUMP=custom@222.201.144.188:22
HDL_CONTROL=${HDL_SHARED_CONTROL:-}
if [ -z "$HDL_CONTROL" ]; then HDL_CONTROL=$(mktemp -d /tmp/hdl-api.XXXXXX); fi
HDL_SSH_OPTS=(-o ControlMaster=auto -o ControlPersist=1200 -o "ControlPath=$HDL_CONTROL/%C" -o "ProxyJump=$HDL_JUMP")
hdl_disconnect() { ssh "${HDL_SSH_OPTS[@]}" -O exit "$HDL_REMOTE" >/dev/null 2>&1 || true; rmdir "$HDL_CONTROL" 2>/dev/null || true; }
trap hdl_disconnect EXIT
HDL_PACKAGE=/Users/DDXQL/Developer/transfer-outbox/api-common-v5-20261111.zip
cd "$HDL_ROOT"
exec > >(tee -a reports/api-common-20261111/user-transfer.log) 2>&1
"$HDL_PY" -B tools/api_reliability_next.py check-only > /dev/null
"$HDL_PY" -B tools/api_reliability_next.py bundle --mac-export "$HDL_MAC_EXPORT"
HDL_SHA=$(shasum -a 256 "$HDL_PACKAGE" | cut -d' ' -f1)
HDL_UPLOAD="api-common-v5-upload-$(date +%Y%m%d-%H%M%S)-$$.zip"
# Each failed upload remains under its own name; existing archives/results are not overwritten.
scp "${HDL_SSH_OPTS[@]}" "$HDL_PACKAGE" "$HDL_REMOTE:/public2/home/qiuqian/hdl-deploy/$HDL_UPLOAD"
ssh "${HDL_SSH_OPTS[@]}" "$HDL_REMOTE" "cd /public2/home/qiuqian/hdl-deploy && printf '%s  %s\\n' '$HDL_SHA' '$HDL_UPLOAD' | sha256sum -c - && if [ ! -e api-common-v5-20261111 ]; then mkdir api-common-v5-20261111 && /public2/home/qiuqian/hdl-envs/portable-v2/bin/python -m zipfile -e '$HDL_UPLOAD' api-common-v5-20261111; fi && cd api-common-v5-20261111 && /public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B tools/api_reliability_next.py check-only --site cluster"
ssh "${HDL_SSH_OPTS[@]}" "$HDL_REMOTE" 'cd /public2/home/qiuqian/hdl-deploy/api-common-v5-20261111 && /public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B deploy/api-common/inspect_remote.py --require-idle' \
 > reports/api-common-20261111/remote-inventory.json
if [ "$HDL_ACTION" = run ]; then
  ssh "${HDL_SSH_OPTS[@]}" "$HDL_REMOTE" 'cd /public2/home/qiuqian/hdl-deploy/api-common-v5-20261111 && mkdir -p logs && mkdir .submission.claim && sbatch --parsable deploy/api-common/cluster.sbatch' \
   | tee reports/api-common-20261111/user-submit.txt
else
  # A new Slurm job may resume only the same safely paused controller and remaining fixed slots.
  ssh "${HDL_SSH_OPTS[@]}" "$HDL_REMOTE" 'cd /public2/home/qiuqian/hdl-deploy/api-common-v5-20261111 && /public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B -c '\''import json,pathlib; s=json.loads((pathlib.Path.home()/"hdl-api-validation/mac-cluster-api-v5-20261111/cluster/ledger.json").read_text()); assert s["status"]=="paused" and all(r["status"]=="passed" for r in s["records"]); pathlib.Path(".resume-prefix-"+str(len(s["records"]))+".claim").mkdir()'\'' && sbatch --parsable deploy/api-common/cluster.sbatch resume' \
   | tee reports/api-common-20261111/user-resume-submit.txt
fi
