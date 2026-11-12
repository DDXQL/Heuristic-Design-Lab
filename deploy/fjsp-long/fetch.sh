#!/usr/bin/env bash
# Run on Mac. Copies only an exited run to a new directory; no --delete.
set -euo pipefail
set +x
HDL_JOB=${1:?job ID}
HDL_REMOTE_RUN=${2:?absolute remote run directory}
HDL_DEST=${3:?new local destination}
case "$HDL_JOB" in ''|*[!0-9]*) exit 2;; esac
case "$HDL_REMOTE_RUN" in /public2/home/qiuqian/*) ;; *) exit 2;; esac
case "$HDL_REMOTE_RUN" in *[!a-zA-Z0-9_./-]*) exit 2;; esac
test ! -e "$HDL_DEST"
HDL_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 -J custom@222.201.144.188 qiuqian@110.1.2.1)
HDL_QUEUE=$("${HDL_SSH[@]}" "squeue -h -u qiuqian -o %i")
for HDL_QUEUED_ID in $HDL_QUEUE; do
  if [ "$HDL_QUEUED_ID" = "$HDL_JOB" ]; then printf '%s\n' 'Job still active; wait for safe pause/exit before full retrieval.' >&2; exit 2; fi
done
mkdir -p "$HDL_DEST"
"${HDL_SSH[@]}" "sacct -j $HDL_JOB --format=JobID,State,ExitCode,Elapsed,AllocCPUS,MaxRSS,NodeList" > "$HDL_DEST/slurm-accounting.txt"
"${HDL_SSH[@]}" "sacct -n -P -j $HDL_JOB --format=JobIDRaw,State,ExitCode" > "$HDL_DEST/slurm-terminal.psv"
python3 - "$HDL_DEST/slurm-terminal.psv" "$HDL_JOB" <<'PY'
import sys
rows=[r.split('|') for r in open(sys.argv[1]).read().splitlines()]
state=next((r[1].split()[0] for r in rows if r[0]==sys.argv[2]),None)
if state not in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}:
    raise SystemExit('Terminal accounting is missing/uncertain; investigate before retrieval or resubmission.')
PY
scp -r -o BatchMode=yes -o ProxyJump=custom@222.201.144.188 "qiuqian@110.1.2.1:$HDL_REMOTE_RUN" "$HDL_DEST/run"
# Verify local result hashes without executing constructors or model clients.
python3 - "$HDL_DEST/run" <<'PY'
import hashlib,json,sys
from pathlib import Path
d=Path(sys.argv[1]);p=json.loads((d/'checkpoint.json').read_text())
for row in p['evaluations'].values():
    f=(d/row['path']).resolve()
    if not f.is_relative_to(d.resolve()) or hashlib.sha256(f.read_bytes()).hexdigest()!=row['sha256']:
        raise SystemExit('result hash/path mismatch')
print('Result hashes verified; inspect checkpoint phase, unknown sends and writer lock before any resume.')
PY
