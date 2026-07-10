#!/bin/bash
set -Eeuo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

QUEUE_LOCK_FILE="${ARGUS_BACKGROUND_QUEUE_LOCK_FILE:-/tmp/argus-background-jobs.lock}"
QUEUE_WAIT_SECONDS="${ARGUS_BACKGROUND_QUEUE_WAIT_SECONDS:-900}"

usage() {
    echo "Usage: $0 <job-name> <command> [args...]" >&2
}

if [ "$#" -lt 2 ]; then
    usage
    exit 64
fi

JOB_NAME="$1"
shift

case "$JOB_NAME" in
    argus-[a-z0-9-]*) ;;
    *)
        echo "ERROR: invalid job name: $JOB_NAME" >&2
        exit 64
        ;;
esac

if ! [[ "$QUEUE_WAIT_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "ERROR: ARGUS_BACKGROUND_QUEUE_WAIT_SECONDS must be a non-negative integer." >&2
    exit 64
fi

JOB_LOCK_FILE="/tmp/${JOB_NAME}.lock"

exec 8>"$JOB_LOCK_FILE"
if ! flock -n 8; then
    echo "Queue[$JOB_NAME]: duplicate job is already running or waiting; skipping."
    exit 0
fi

WAIT_STARTED_AT="$(date +%s)"
exec 9>"$QUEUE_LOCK_FILE"
echo "Queue[$JOB_NAME]: waiting up to ${QUEUE_WAIT_SECONDS}s for the background-job lock."

if ! flock -w "$QUEUE_WAIT_SECONDS" 9; then
    echo "ERROR: Queue[$JOB_NAME] timed out waiting for $QUEUE_LOCK_FILE." >&2
    exit 75
fi

WAIT_FINISHED_AT="$(date +%s)"
WAITED_SECONDS=$((WAIT_FINISHED_AT - WAIT_STARTED_AT))
echo "Queue[$JOB_NAME]: acquired background-job lock after ${WAITED_SECONDS}s."

echo "Queue[$JOB_NAME]: starting command: $*"
set +e
"$@"
COMMAND_STATUS=$?
set -e

echo "Queue[$JOB_NAME]: command finished with exit status $COMMAND_STATUS."
exit "$COMMAND_STATUS"
