# Setup — new machine for Open Brain + Claude Code

The backend (FastAPI + worker + Postgres + web) runs on the GCP VM at
`0xpai.com`. Every machine you use just talks to that backend, so per-machine
setup is short — five steps, under ten minutes.

## 1. Clone the repo

```bash
git clone git@github.com:shu/open-brain.git ~/projects/open-brain
```

## 2. Symlink the SessionEnd + SessionStart hooks

The hook scripts live in the repo so fixes propagate via `git pull` and the
repo→project mapping is identical on every machine. Symlink both into the
Claude Code hooks directory:

```bash
mkdir -p ~/.claude/hooks
ln -s ~/projects/open-brain/scripts/claude-code/session-end-ingest.sh \
      ~/.claude/hooks/session-end-ingest.sh
ln -s ~/projects/open-brain/scripts/claude-code/session-start-distill.sh \
      ~/.claude/hooks/session-start-distill.sh
```

The SessionStart hook is **self-scoping** — it only fires inside the
open-brain repo (it checks `cwd` against its own location) so it's safe to
install globally. In other repos it exits immediately and silently.

## 3. Drop the env file

Create `~/.claude/openbrain.env` (chmod 600) with:

```bash
OPENBRAIN_API_URL=https://0xpai.com
OPENBRAIN_API_KEY=<from 1Password>

# Pick how the SessionEnd hook talks to Haiku:
#   cli  — shell out to `claude --print`; cost lands on Claude Code subscription (default)
#   api  — direct REST call; requires ANTHROPIC_API_KEY; pay-per-token billing
#   auto — cli if `claude` is on PATH, else api
OB_SESSION_END_BACKEND=cli

# Only required when OB_SESSION_END_BACKEND=api (or auto with no CLI installed):
# ANTHROPIC_API_KEY=<from 1Password — Anthropic console>
```

The hook sources this file at every SessionEnd. `OPENBRAIN_API_KEY` is the
Open Brain backend key (always required). The Haiku summarisation backend is
configurable — `cli` is the default and stays within your subscription; `api`
costs roughly $0.05 per session via pay-per-token credits.

If the chosen backend can't run (CLI missing, or API key missing) the hook
logs the reason to `/tmp/ob-session-end.log` and silently skips that session
— SessionEnd hooks are fire-and-forget.

## 4. Add the Open Brain MCP server

```bash
claude mcp add open-brain -- \
  /home/$USER/projects/open-brain/.venv/bin/python \
  /home/$USER/projects/open-brain/src/mcp_server.py
```

(Or copy the entry from another machine's `~/.claude/mcp.json` — the command +
env are stable.)

The MCP server picks up `OPENBRAIN_API_URL` / `OPENBRAIN_API_KEY` from its env;
either set them in your shell rc, or pass them via the MCP server entry's
`env` block.

## 5. Wire the SessionEnd + SessionStart hooks into Claude Code settings

Edit `~/.claude/settings.json` and add both hook entries:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/session-start-distill.sh"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/session-end-ingest.sh"
          }
        ]
      }
    ]
  }
}
```

(Merge into your existing `hooks` block if present.)

**What each hook does:**

- **SessionEnd** — at session exit, Haiku summarises the transcript and posts
  it to Open Brain (vector DB + `context/sessions/{date}.md`).
- **SessionStart** — at session open, fires the daily distill in the background
  if there's pending work and the sentinel is older than 6 hours (configurable
  via `OB_SESSION_START_MIN_HOURS`). This makes STATE.md catch up the moment
  you start working, even if anacron/cron didn't run overnight.

The SessionStart hook only fires on `source=startup` — resume/clear/compact
don't trigger redundant runs.

## Verify

**SessionEnd:** open a Claude Code session in `~/projects/open-brain`, do
one substantive thing, then exit normally. Within ~30 seconds:

```bash
tail /tmp/ob-session-end.log               # should show "memory_ingested raw_id=..."
ls context/sessions/                       # should show today's file
curl -s -H "X-API-Key: $OPENBRAIN_API_KEY" \
  "$OPENBRAIN_API_URL/v1/memory/recent?limit=1" | jq .
```

The latest memory should have `source=claude-code-session` and
`project=open-brain`.

**SessionStart:** open a *fresh* CC session in the same repo. Within a few
seconds:

```bash
tail /tmp/ob-session-start.log             # one of:
                                           #   "firing background distill (pending=N, ...)"
                                           #   "skip: sentinel age=... (throttle)"
                                           #   "skip: no pending sessions"
make memory-state                          # Distill last run should advance
```

If you open CC in a different repo (e.g. `~/projects/egle-climbing`) the
SessionStart hook silently no-ops — nothing is logged, no distill fires.

## Per-machine vs. version-controlled

What you set up here, and where it lives:

| Thing | In git? | Why |
|---|---|---|
| SessionEnd + SessionStart hooks + Python worker | ✅ Yes (`scripts/claude-code/`) | Fixes propagate via `git pull`; identical on all machines |
| Memory-flywheel run scripts + state inspector | ✅ Yes (`scripts/memory/`) | Same |
| Repo→project mapping (`REPO_PROJECT_MAP`) | ✅ Yes (in `session_end_ingest.py`) | Add a project once, available on all machines |
| `context/STATE.md`, `DECISIONS.md` | ✅ Yes | Travels with the codebase |
| `context/sessions/{date}.md` | ❌ No (gitignored) | High churn, low durable value — summaries live in `memory_items` |
| `context/.last-distill`, `.last-curate` | ❌ No (gitignored) | Per-machine catch-up state |
| `~/.claude/openbrain.env` | ❌ No (per-machine) | Contains API keys |
| `~/.claude/projects/.../memory/*.md` | ❌ No (per-machine) | Vector DB is the cross-machine source of truth; markdown layer can diverge |
| `/etc/cron.d/ob-memory-flywheel`, anacron entries | ❌ No (per-machine) | Installed by `make memory-install-cron`; written outside the repo |

The personal markdown layer is intentionally *not* synced across machines —
the vector DB already syncs (it's cloud), so cross-machine recall happens via
`search_memory`. Letting the markdown layer diverge per machine is a feature:
it creates a natural privacy boundary (work PC ≠ home PC) and avoids merge
conflicts.

## Adding a new repo to the project mapping

Edit `REPO_PROJECT_MAP` in `scripts/claude-code/session_end_ingest.py`,
commit, push. Every machine picks it up on the next `git pull`. No JSON file,
no dynamic discovery — one line per repo, by `basename($CLAUDE_PROJECT_DIR)`.

## Memory flywheel — cron + on-demand

The daily/weekly memory jobs run **locally on your laptop** because they need
access to `~/.claude/projects/.../memory/` and `context/sessions/` — neither
is reachable from the VM or from Anthropic's hosted scheduler.

### On-demand commands (use these any time)

```bash
make memory-state          # see last-run dates, pending sessions, file sizes vs caps
make memory-distill        # run daily distillation right now
make memory-curate         # run weekly curator right now
make memory-logs           # summary of recent runs
make memory-tail           # live-tail /tmp/ob-memory-*.log
make memory-clean-logs     # truncate the log files
```

### One-time cron setup (catch-up-safe)

```bash
# 1. Make sure cron + anacron are installed (anacron handles missed runs).
sudo apt install -y cron anacron

# 2. Install the schedule entries.
make memory-install-cron

# 3. WSL2 only: tell WSL to start cron on boot.
sudo tee /etc/wsl.conf > /dev/null <<'EOF'
[boot]
command = "service cron start"
EOF

# Then close all WSL windows and run `wsl --shutdown` from Windows PowerShell.
# Next time you open a terminal cron will be running.
```

### What gets installed

`make memory-install-cron` writes:

- `/etc/cron.d/ob-memory-flywheel` — fires `run-distill.sh` at 23:00 daily and
  `run-curate.sh` at Sunday 09:00.
- `/etc/anacrontab` entries — if the machine was off at the scheduled time,
  anacron runs the job ~10 minutes after the next boot.

Both jobs are **idempotent**:
- The daily distill uses a sentinel file (`context/.last-distill`) to figure
  out which session logs are unprocessed, so it picks up exactly where it
  left off — whether that's "today" or "12 days ago."
- The weekly curator is stateless; running it twice in a row produces the
  same result as running it once.

So missing a Sunday or two costs at most a Haiku call's worth of drift; the
next run reconciles everything.

Remove the cron entries any time with:

```bash
make memory-uninstall-cron
```
