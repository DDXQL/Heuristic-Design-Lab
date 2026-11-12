#!/usr/bin/env bash
# User-run transfer / one replay-evaluation job, never repeats the Mac phase.
set -euo pipefail
set +x
unset LEAFAPI_API_KEY
if [ "$#" -ne 4 ] || [ "$2" != --allow-evaluation ] || [ "$3" != --approve-solves ] || [ "$4" != 12 ]; then
 printf '%s\n' 'Usage: submit_cluster.sh run|resume --allow-evaluation --approve-solves 12' >&2; exit 2
fi
HDL_ACTION=$1
case "$HDL_ACTION" in run|resume) ;; *) exit 2;; esac
HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd);cd "$HDL_ROOT"
HDL_PY=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python
HDL_EXPORT="$HOME/hdl-flow-validation/fjsp-state-a-flow-20261112/mac/export.json"
"$HDL_PY" -B tools/flow_check.py check-mac-export --mac-export "$HDL_EXPORT"
HDL_HASH=$(shasum -a 256 "$HDL_EXPORT" | cut -d' ' -f1)
HDL_REMOTE=qiuqian@110.1.2.1
HDL_CONTROL=${HDL_SHARED_CONTROL:-}
if [ -z "$HDL_CONTROL" ]; then HDL_CONTROL=$(mktemp -d /tmp/hdl-flow.XXXXXX); fi
HDL_SSH=(-o ControlMaster=auto -o ControlPersist=1800 -o "ControlPath=$HDL_CONTROL/%C" -o ProxyJump=custom@222.201.144.188:22)
hdl_cleanup() { ssh "${HDL_SSH[@]}" -O exit "$HDL_REMOTE" >/dev/null 2>&1 || true; rmdir "$HDL_CONTROL" 2>/dev/null || true; }
trap hdl_cleanup EXIT
HDL_LOG="reports/flow-check-20261112/transfer-$(date +%Y%m%d-%H%M%S)-$$";mkdir "$HDL_LOG"
exec > >(tee -a "$HDL_LOG/user-transfer.log") 2>&1
ssh "${HDL_SSH[@]}" "$HDL_REMOTE" 'mkdir -p /public2/home/qiuqian/hdl-deploy/fjsp-state-a-flow-20261112/exports'
HDL_TEMP="incoming-$(date +%Y%m%d-%H%M%S)-$$.json"
scp "${HDL_SSH[@]}" "$HDL_EXPORT" "$HDL_REMOTE:/public2/home/qiuqian/hdl-deploy/fjsp-state-a-flow-20261112/exports/$HDL_TEMP"
HDL_JOB=$(ssh "${HDL_SSH[@]}" "$HDL_REMOTE" "set -e; cd /public2/home/qiuqian/hdl-deploy/fjsp-state-a-flow-20261112; printf '%s  %s\\n' '$HDL_HASH' 'exports/$HDL_TEMP' | sha256sum -c - >&2; ln exports/'$HDL_TEMP' exports/mac-'$HDL_HASH'.json 2>/dev/null || test \"\$(sha256sum exports/mac-'$HDL_HASH'.json | cut -d' ' -f1)\" = '$HDL_HASH'; /public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B tools/flow_check.py check-mac-export --mac-export exports/mac-'$HDL_HASH'.json >&2; HDL_QUEUE=\$(squeue -u qiuqian -h); if [ -n \"\$HDL_QUEUE\" ]; then printf '%s\\n' 'Existing personal jobs: Mac results preserved; do not rerun Mac.' >&2; exit 3; fi; mkdir -p logs; if [ '$HDL_ACTION' = run ]; then mkdir .submission.claim; else /public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B -c 'import json,pathlib; s=json.loads((pathlib.Path.home()/\"hdl-flow-validation/fjsp-state-a-flow-20261112/cluster/checkpoint.json\").read_text()); assert s[\"phase\"]==\"paused\"; pathlib.Path(\".resume-prefix-\"+str(s[\"cursor\"])+\".claim\").mkdir()'; fi; sbatch --no-requeue --parsable deploy/flow-check/cluster.sbatch '$HDL_ACTION' exports/mac-'$HDL_HASH'.json")
printf '%s\n' "$HDL_JOB" | tee "$HDL_LOG/job-id.txt"
printf '%s\n' "$HDL_JOB" >> reports/flow-check-20261112/submitted-jobs.txt
if ! ssh "${HDL_SSH[@]}" "$HDL_REMOTE" "scontrol show job '$HDL_JOB'" > "$HDL_LOG/job-after-submit.txt" 2>&1; then
  # An immediately completed job may already have left the active controller.
  # Preserve its ID and accounting; never submit it again to obtain a status.
  ssh "${HDL_SSH[@]}" "$HDL_REMOTE" "sacct -X -j '$HDL_JOB' --format=JobID,State,ExitCode,Elapsed" > "$HDL_LOG/accounting-after-submit.txt" 2>&1 || true
fi
