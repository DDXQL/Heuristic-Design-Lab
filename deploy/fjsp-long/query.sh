#!/usr/bin/env bash
# Read-only metadata. Missing squeue ID is not an API failure.
set -euo pipefail
HDL_JOB=${1:?job ID}
case "$HDL_JOB" in ''|*[!0-9]*) exit 2;; esac
squeue -j "$HDL_JOB" -o '%.18i %.12T %.10M %.6C %.20R'
sacct -j "$HDL_JOB" --format=JobID,JobName,State,ExitCode,Elapsed,AllocCPUS,MaxRSS,NodeList
