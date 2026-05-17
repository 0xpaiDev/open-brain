#!/usr/bin/env bash
# SessionEnd hook for Claude Code — captures a structured Haiku summary of
# the just-finished session into Open Brain memory (and the project-local
# context/sessions/ log when the repo opted in by creating context/).
#
# Wired up via ~/.claude/settings.json:
#   {"hooks": {"SessionEnd": [{"hooks": [{"type": "command",
#     "command": "bash ~/.claude/hooks/session-end-ingest.sh"}]}]}}
#
# Symlinked from this repo on each machine:
#   ln -s ~/projects/open-brain/scripts/claude-code/session-end-ingest.sh \
#         ~/.claude/hooks/session-end-ingest.sh
#
# Reads the SessionEnd hook payload (JSON) from stdin and forwards everything
# to session_end_ingest.py. Logs to /tmp/ob-session-end.log. Never blocks the
# CC exit path — always exits 0 regardless of inner failures.

set -u
LOG=/tmp/ob-session-end.log

# Resolve the directory of the real script even when invoked via symlink.
SCRIPT_PATH="$(readlink -f -- "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname -- "$SCRIPT_PATH")"

# Per-machine env (OPENBRAIN_API_URL, OPENBRAIN_API_KEY, ANTHROPIC_API_KEY).
ENV_FILE="${OB_SESSION_END_ENV:-$HOME/.claude/openbrain.env}"
if [ -r "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a
  . "$ENV_FILE"
  set +a
fi

{
  echo "---- $(date -u +%Y-%m-%dT%H:%M:%SZ) session-end-ingest start ----"
} >> "$LOG" 2>&1

PYTHON_BIN="${OB_SESSION_END_PYTHON:-python3}"

# Pipe stdin (hook payload JSON) into the worker. The worker is responsible
# for being fire-and-forget; we ignore its exit status.
"$PYTHON_BIN" "$SCRIPT_DIR/session_end_ingest.py" >> "$LOG" 2>&1 || true

echo "---- $(date -u +%Y-%m-%dT%H:%M:%SZ) session-end-ingest done ----" >> "$LOG"

exit 0
