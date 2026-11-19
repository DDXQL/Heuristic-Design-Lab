#!/usr/bin/env bash
set -euo pipefail
set +x

# Scheduler probe only. Uses neither experiment inputs nor account files.
ROOT=$(cd -- "${1:?release root}" && pwd -P)
PARTITION=${2:?partition}
ACCOUNT=${3:?account}
QOS=${4:?qos}
DIR=${5:-}
PARENT=${6:-}
JOB=${SLURM_JOB_ID:-}
[[ $JOB =~ ^[0-9]+$ ]]

OPTIONS=(--parsable --no-requeue --nodes=1 --ntasks=1 --cpus-per-task=1
         --mem=1024M --time=00:05:00 "--partition=$PARTITION"
         "--account=$ACCOUNT" "--qos=$QOS" "--chdir=$ROOT")
squeue -h -j "$JOB" -o 'job=%i state=%T time_left=%L'
scontrol -o show job "$JOB"

if [[ -z $DIR ]]; then
    mkdir -p "$ROOT/reports/r15-slurm-smoke"
    DIR=$(mktemp -d "$ROOT/reports/r15-slurm-smoke/${JOB}.XXXXXX")
    (set -C; printf '%s\n' "$JOB" > "$DIR/parent.ready")
    CHILD=$(sbatch "${OPTIONS[@]}" "--dependency=afterany:$JOB" --job-name=r15-smoke-child \
        "--output=$DIR/child-%j.out" "--error=$DIR/child-%j.err" \
        "$ROOT/experiments/triad/candidate_slurm_smoke.sbatch" \
        "$ROOT" "$PARTITION" "$ACCOUNT" "$QOS" "$DIR" "$JOB")
    CHILD=${CHILD%%;*}
    [[ $CHILD =~ ^[0-9]+$ ]]
    (set -C; printf '%s\n' "$CHILD" > "$DIR/child.submitted")
    printf 'PARENT=%s CHILD=%s RECEIPTS=%s\n' "$JOB" "$CHILD" "$DIR"
else
    [[ $DIR == "$ROOT/reports/r15-slurm-smoke/"* && $PARENT =~ ^[0-9]+$ ]]
    [[ $(cat "$DIR/parent.ready") == "$PARENT" ]]
    DEADLINE=$((SECONDS + 45))
    RECORD=
    while (( SECONDS < DEADLINE )); do
        RECORD=$(sacct -n -P -X -j "$PARENT" --format=JobIDRaw,State,ExitCode |
            awk -F'|' -v parent="$PARENT" '$1 == parent && $2 == "COMPLETED" && $3 == "0:0" {print}')
        if [[ -n $RECORD && -f $DIR/child.submitted ]] &&
           [[ $(cat "$DIR/child.submitted") == "$JOB" ]]; then
            (set -C; printf 'PASS parent=%s child=%s accounting=%s API=0 solves=0\n' \
                "$PARENT" "$JOB" "$RECORD" > "$DIR/child.passed")
            cat "$DIR/child.passed"
            exit 0
        fi
        sleep 2
    done
    printf 'Scheduler accounting or child receipt did not match within 45 seconds\n' >&2
    exit 2
fi
