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

# Buffer the hook payload (stdin JSON) into a tempfile so we can fully detach
# the worker. A backgrounded child whose stdin came from the parent's pipe
# sees EOF immediately when the parent exits, so we can't rely on the pipe
# surviving — write to disk, redirect the detached child from the file.
PAYLOAD_TMP="$(mktemp /tmp/ob-session-end-payload.XXXXXX.json)"
cat > "$PAYLOAD_TMP" 2>/dev/null || true

# Fully detach the worker. CC's hook executor times out around 60s, but
# Haiku summarisation of a large transcript can take 60-120s. The detached
# child owns its payload tempfile and cleans it up after writing the done
# marker.
nohup bash -c '
  "$1" "$2" < "$3" >> "$4" 2>&1
  echo "---- $(date -u +%Y-%m-%dT%H:%M:%SZ) session-end-ingest done ----" >> "$4"
  rm -f "$3" 2>/dev/null || true
' _ "$PYTHON_BIN" "$SCRIPT_DIR/session_end_ingest.py" "$PAYLOAD_TMP" "$LOG" \
  >> "$LOG" 2>&1 &
disown 2>/dev/null || true

exit 0
