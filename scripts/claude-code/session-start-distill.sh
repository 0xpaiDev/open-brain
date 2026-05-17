#!/usr/bin/env bash
# SessionStart hook — opportunistic memory distill catch-up.
#
# Fires `scripts/memory/run-distill.sh` in the background when:
#   (a) the new CC session's cwd matches the repo this script lives in
#       (so the hook is safe to install globally — only fires for open-brain)
#   (b) the repo has opted in (a context/sessions/ directory exists)
#   (c) the hook source is "startup" (not resume / clear / compact)
#   (d) at least one session log is newer than context/.last-distill
#   (e) the sentinel was last updated more than MIN_HOURS_BETWEEN ago
#       (throttle — opening 6 sessions in an afternoon shouldn't burn 6 runs)
#
# Otherwise exits 0 silently. Always exits 0 — SessionStart must never block.
# All logging goes to /tmp/ob-session-start.log.
#
# Wired up via ~/.claude/settings.json:
#   {"hooks": {"SessionStart": [{"hooks": [{"type": "command",
#     "command": "bash ~/.claude/hooks/session-start-distill.sh"}]}]}}
#
# Symlinked from the repo:
#   ln -s ~/projects/open-brain/scripts/claude-code/session-start-distill.sh \
#         ~/.claude/hooks/session-start-distill.sh

set -u

LOG=/tmp/ob-session-start.log
LOCK=/tmp/ob-session-start.lock
MIN_HOURS_BETWEEN="${OB_SESSION_START_MIN_HOURS:-6}"

# ── Single-fire lock (parallel CC windows shouldn't pile up) ──────────────────

exec 9>"$LOCK" 2>/dev/null || exit 0
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || exit 0
fi

# ── Read hook payload (JSON on stdin) ─────────────────────────────────────────

PAYLOAD=""
if [ ! -t 0 ]; then
  PAYLOAD="$(cat 2>/dev/null || true)"
fi

HOOK_CWD=""
HOOK_SOURCE=""
if [ -n "$PAYLOAD" ] && command -v python3 >/dev/null 2>&1; then
  HOOK_CWD="$(
    printf '%s' "$PAYLOAD" | python3 -c \
      'import json,sys
try:
    d = json.loads(sys.stdin.read() or "{}")
    print(d.get("cwd", ""))
except Exception:
    pass' 2>/dev/null || true
  )"
  HOOK_SOURCE="$(
    printf '%s' "$PAYLOAD" | python3 -c \
      'import json,sys
try:
    d = json.loads(sys.stdin.read() or "{}")
    print(d.get("source", ""))
except Exception:
    pass' 2>/dev/null || true
  )"
fi
[ -z "$HOOK_CWD" ] && HOOK_CWD="${CLAUDE_PROJECT_DIR:-$(pwd)}"
HOOK_CWD="$(readlink -f -- "$HOOK_CWD" 2>/dev/null || echo "$HOOK_CWD")"

NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Only act on a fresh start — resume / clear / compact reuse existing context
# and shouldn't trigger a fresh distill (the previous SessionEnd handled it).
if [ -n "$HOOK_SOURCE" ] && [ "$HOOK_SOURCE" != "startup" ]; then
  echo "[$NOW_TS] skip: hook_source=$HOOK_SOURCE" >> "$LOG"
  exit 0
fi

# ── Self-scope: only fire in the repo where this script actually lives ────────

SCRIPT_PATH="$(readlink -f -- "${BASH_SOURCE[0]}")"
SCRIPT_REPO="$(cd "$(dirname -- "$SCRIPT_PATH")/../.." && pwd)"
SCRIPT_REPO="$(readlink -f -- "$SCRIPT_REPO" 2>/dev/null || echo "$SCRIPT_REPO")"

if [ "$HOOK_CWD" != "$SCRIPT_REPO" ]; then
  # Different repo — leave it alone. Don't even log; this would spam /tmp.
  exit 0
fi
if [ ! -d "$SCRIPT_REPO/context/sessions" ]; then
  echo "[$NOW_TS] skip: repo has no context/sessions/ (not opted in)" >> "$LOG"
  exit 0
fi

# ── Throttle: skip if sentinel was bumped within MIN_HOURS_BETWEEN ────────────

SENTINEL="$SCRIPT_REPO/context/.last-distill"
NOW_EPOCH="$(date +%s)"
if [ -f "$SENTINEL" ]; then
  SENT_MTIME="$(stat -c %Y "$SENTINEL" 2>/dev/null || echo "$NOW_EPOCH")"
  AGE_S=$(( NOW_EPOCH - SENT_MTIME ))
  THRESHOLD_S=$(( MIN_HOURS_BETWEEN * 3600 ))
  if [ "$AGE_S" -lt "$THRESHOLD_S" ]; then
    echo "[$NOW_TS] skip: sentinel age=${AGE_S}s < ${THRESHOLD_S}s (throttle)" >> "$LOG"
    exit 0
  fi
fi

# ── Skip when there's nothing to do ───────────────────────────────────────────

if [ -f "$SENTINEL" ]; then
  PENDING="$(find "$SCRIPT_REPO/context/sessions" -name '*.md' -newer "$SENTINEL" 2>/dev/null | wc -l | tr -d ' ')"
else
  PENDING="$(find "$SCRIPT_REPO/context/sessions" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"
fi
if [ "${PENDING:-0}" = "0" ]; then
  echo "[$NOW_TS] skip: no pending sessions" >> "$LOG"
  exit 0
fi

# ── Fire ──────────────────────────────────────────────────────────────────────

# Source per-machine env (so the subscription/api backend is correctly chosen
# inside run-distill.sh's `claude` invocation).
ENV_FILE="${OB_SESSION_END_ENV:-$HOME/.claude/openbrain.env}"
if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

echo "[$NOW_TS] firing background distill (pending=$PENDING, hook_source=${HOOK_SOURCE:-startup})" >> "$LOG"

# Fully detach — SessionStart must return immediately. nohup + & + disown
# means the distill keeps running after CC's hook subprocess exits.
nohup bash "$SCRIPT_REPO/scripts/memory/run-distill.sh" >> "$LOG" 2>&1 &
disown 2>/dev/null || true

exit 0
