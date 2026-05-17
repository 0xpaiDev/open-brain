#!/usr/bin/env python3
"""Show the current state of the memory flywheel — for `make memory-state`.

Prints, in human-readable form:

  Distill last run    : YYYY-MM-DD  (N day(s) ago)
  Curate  last run    : YYYY-MM-DD  (N day(s) ago)
  Sessions pending    : N files since last distill
  STATE.md            : X / 2,500 chars (NN%)
  DECISIONS.md        : X / 5,000 chars (NN%)

  Personal layer (~/.claude/projects/-home-shu-projects-open-brain/memory/):
    user_profile.md            : X / 1,500 chars (NN%)
    ops_deployment.md          : X / 2,500 chars (NN%)
    feedback_*.md              : (4 files, total X chars)
    ...
    MEMORY.md                  : X / 200 lines (NN%)

  Recent distill log (last 5 runs)
    2026-05-17T22:00Z   exit=0   duration=23s
    ...

No external deps. Reads files only — never writes.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

# ── Layout ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_DIR = REPO_ROOT / "context"
SESSIONS_DIR = CONTEXT_DIR / "sessions"
DISTILL_SENTINEL = CONTEXT_DIR / ".last-distill"
CURATE_SENTINEL = CONTEXT_DIR / ".last-curate"
STATE_FILE = CONTEXT_DIR / "STATE.md"
DECISIONS_FILE = CONTEXT_DIR / "DECISIONS.md"

PERSONAL_DIR = Path.home() / ".claude/projects/-home-shu-projects-open-brain/memory"

DISTILL_LOG = Path("/tmp/ob-memory-distill.log")
CURATE_LOG = Path("/tmp/ob-memory-curate.log")

# Per-file caps mirror cron/jobs/weekly-memory-curator.md.
PERSONAL_CAPS: dict[str, int] = {
    "user_profile.md": 1500,
    "ops_deployment.md": 2500,
    "learning.md": 2500,
    "config_auto_capture.md": 1500,
    "project_synthesis_model.md": 2500,
    "project_sequence.md": 2500,
    "project_web_dashboard.md": 2500,
    "feedback_multi_agent_workflow.md": 1500,
    "feedback_architect_role.md": 1500,
    "feedback_plan_location.md": 1500,
}
PROJECT_PREFIX_CAP = ("project_", 2500)
FEEDBACK_PREFIX_CAP = ("feedback_", 1500)
MEMORY_INDEX_LINE_CAP = 200

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fmt_age(d: date | None) -> str:
    if d is None:
        return "(never)"
    delta = (date.today() - d).days
    if delta == 0:
        word = "today"
    elif delta == 1:
        word = "yesterday"
    else:
        word = f"{delta} days ago"
    return f"{d.isoformat()}  ({word})"


def _read_sentinel(path: Path) -> date | None:
    if not path.is_file():
        return None
    try:
        return date.fromisoformat(path.read_text().strip().split()[0])
    except (ValueError, IndexError):
        return None


def _char_count(path: Path) -> int:
    try:
        return len(path.read_text())
    except OSError:
        return 0


def _line_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def _pct(value: int, cap: int) -> str:
    if cap <= 0:
        return "—"
    return f"{int(round(100 * value / cap))}%"


def _cap_for(name: str) -> int | None:
    if name in PERSONAL_CAPS:
        return PERSONAL_CAPS[name]
    if name.startswith(FEEDBACK_PREFIX_CAP[0]):
        return FEEDBACK_PREFIX_CAP[1]
    if name.startswith(PROJECT_PREFIX_CAP[0]):
        return PROJECT_PREFIX_CAP[1]
    return None


def _pending_sessions(last_distill: date | None) -> list[Path]:
    """Session log files newer than the last successful distill."""
    if not SESSIONS_DIR.is_dir():
        return []
    cutoff = last_distill or (date.today())
    out: list[Path] = []
    for p in sorted(SESSIONS_DIR.glob("*.md")):
        try:
            file_date = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if file_date > cutoff:
            out.append(p)
    return out


def _tail_runs(log_path: Path, n: int = 5) -> list[str]:
    """Extract the last N "done" lines from a run log."""
    if not log_path.is_file():
        return []
    pattern = re.compile(
        r"==== (?P<ts>[^ ]+) (?:[\w-]+) done exit=(?P<exit>\d+) duration=(?P<dur>\d+s) ===="
    )
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return []
    matches = list(pattern.finditer(text))
    out: list[str] = []
    for m in matches[-n:]:
        out.append(f"  {m.group('ts')}   exit={m.group('exit')}   duration={m.group('dur')}")
    return out


# ── Rendering ─────────────────────────────────────────────────────────────────


def _render_header(
    last_distill: date | None, last_curate: date | None, pending: list[Path]
) -> None:
    print("Memory Flywheel — state")
    print(f"  Now                : {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  Distill last run   : {_fmt_age(last_distill)}")
    print(f"  Curate  last run   : {_fmt_age(last_curate)}")
    print(f"  Sessions pending   : {len(pending)} file(s) since last distill")
    for p in pending[:10]:
        print(f"      {p.name}")
    if len(pending) > 10:
        print(f"      ... and {len(pending) - 10} more")
    print()


def _render_project_layer() -> None:
    print("Project layer (context/):")
    if STATE_FILE.is_file():
        n = _char_count(STATE_FILE)
        print(f"  STATE.md           : {n:>5,} / 2,500 chars ({_pct(n, 2500)})")
    else:
        print("  STATE.md           : (missing)")
    if DECISIONS_FILE.is_file():
        n = _char_count(DECISIONS_FILE)
        print(f"  DECISIONS.md       : {n:>5,} / 5,000 chars ({_pct(n, 5000)})")
    else:
        print("  DECISIONS.md       : (missing)")
    print()


def _render_personal_file(path: Path) -> None:
    name = path.name
    if name == "MEMORY.md":
        lines = _line_count(path)
        print(
            f"  {name:<32} : {lines:>5,} / {MEMORY_INDEX_LINE_CAP} lines "
            f"({_pct(lines, MEMORY_INDEX_LINE_CAP)})"
        )
        return
    cap = _cap_for(name)
    n = _char_count(path)
    if cap is None:
        print(f"  {name:<32} : {n:>5,} chars (no cap)")
    else:
        print(f"  {name:<32} : {n:>5,} / {cap:>5,} chars ({_pct(n, cap)})")


def _render_personal_layer() -> None:
    print(f"Personal layer ({PERSONAL_DIR}):")
    if not PERSONAL_DIR.is_dir():
        print("  (directory missing — has the memory layer been initialised?)")
        print()
        return
    for path in sorted(PERSONAL_DIR.glob("*.md")):
        _render_personal_file(path)
    print()


def _render_recent_runs(label: str, log_path: Path) -> None:
    print(f"Recent {label} runs (last 5):")
    runs = _tail_runs(log_path)
    if not runs:
        print("  (no runs yet — log empty or missing)")
    for line in runs:
        print(line)


def main() -> int:
    last_distill = _read_sentinel(DISTILL_SENTINEL)
    last_curate = _read_sentinel(CURATE_SENTINEL)
    pending = _pending_sessions(last_distill)

    _render_header(last_distill, last_curate, pending)
    _render_project_layer()
    _render_personal_layer()
    _render_recent_runs("distill", DISTILL_LOG)
    print()
    _render_recent_runs("curate", CURATE_LOG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
