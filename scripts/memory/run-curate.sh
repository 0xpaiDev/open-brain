#!/usr/bin/env bash
# Run the weekly memory curator job on demand.
#
# Pipes the cron job markdown into `claude --print`. Output is appended to
# /tmp/ob-memory-curate.log with a timestamp header. The job is stateless —
# running it repeatedly is safe; the worst case is one extra Haiku call.
#
# Usage:
#   bash scripts/memory/run-curate.sh
#   make memory-curate

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG=/tmp/ob-memory-curate.log
JOB_FILE="$REPO_ROOT/cron/jobs/weekly-memory-curator.md"
CLAUDE_BIN="${OB_CLAUDE_BIN:-claude}"
# Curator uses Sonnet by default — it's the more thoughtful pass.
MODEL="${OB_CURATE_MODEL:-claude-sonnet-4-6}"

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
  echo "==== $START_TS weekly-curate start ===="
} >> "$LOG"

PROMPT=$(cat <<EOF
You are running the Weekly Memory Curator job for the open-brain repo.

Working directory: $REPO_ROOT
Personal memory layer: \$HOME/.claude/projects/-home-shu-projects-open-brain/memory/

Job specification follows between <job> tags. Execute it exactly. Report the
per-file usage summary at the end of your output (as specified in step 5).

<job>
$(cat "$JOB_FILE")
</job>
EOF
)

cd "$REPO_ROOT" || exit 1
EXIT_CODE=0
echo "$PROMPT" | "$CLAUDE_BIN" --print --model "$MODEL" >> "$LOG" 2>&1 || EXIT_CODE=$?

# Touch the curate sentinel on success so `make memory-state` can show drift.
if [ "$EXIT_CODE" = "0" ]; then
  date -u +%Y-%m-%d > "$REPO_ROOT/context/.last-curate" 2>/dev/null || true
fi

END_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DURATION=$(( $(date +%s) - START_EPOCH ))

{
  echo "==== $END_TS weekly-curate done exit=$EXIT_CODE duration=${DURATION}s ===="
} >> "$LOG"

exit "$EXIT_CODE"
