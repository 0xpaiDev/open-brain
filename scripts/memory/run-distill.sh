#!/usr/bin/env bash
# Run the daily memory distillation job on demand.
#
# Pipes the cron job markdown into `claude --print`. Output (the model's
# response + any reported diffs) is appended to /tmp/ob-memory-distill.log
# with a timestamp header so you can see history.
#
# Usage:
#   bash scripts/memory/run-distill.sh
#   make memory-distill            # same thing via Make
#
# Exits 0 on success, non-zero on failure. Cron callers should ignore exit
# code (they have their own logging); humans should check it.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG=/tmp/ob-memory-distill.log
JOB_FILE="$REPO_ROOT/cron/jobs/daily-memory-distill.md"
CLAUDE_BIN="${OB_CLAUDE_BIN:-claude}"
MODEL="${OB_MEMORY_MODEL:-claude-haiku-4-5}"

if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  echo "error: '$CLAUDE_BIN' not on PATH — install Claude Code CLI" >&2
  exit 127
fi
if [ ! -r "$JOB_FILE" ]; then
  echo "error: job file missing: $JOB_FILE" >&2
  exit 1
fi

START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START_EPOCH="$(date +%s)"

{
  echo
  echo "==== $START_TS daily-distill start ===="
} >> "$LOG"

# Build the prompt: pin the working dir + interpolated job spec, then ask CC
# to execute it. The job markdown already enumerates inputs / steps in
# enough detail for a CC session to follow.
PROMPT=$(cat <<EOF
You are running the Daily Memory Distillation job for the open-brain repo.

Working directory: $REPO_ROOT

Job specification follows between <job> tags. Execute it exactly. Report the
single-line diff summary at the end of your output (as specified in step 6).

<job>
$(cat "$JOB_FILE")
</job>
EOF
)

# --print = non-interactive. --model pins Haiku so this stays cheap.
# The `cd` keeps relative paths in the job spec resolvable.
cd "$REPO_ROOT" || exit 1
EXIT_CODE=0
echo "$PROMPT" | "$CLAUDE_BIN" --print --model "$MODEL" >> "$LOG" 2>&1 || EXIT_CODE=$?

END_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DURATION=$(( $(date +%s) - START_EPOCH ))

{
  echo "==== $END_TS daily-distill done exit=$EXIT_CODE duration=${DURATION}s ===="
} >> "$LOG"

exit "$EXIT_CODE"
