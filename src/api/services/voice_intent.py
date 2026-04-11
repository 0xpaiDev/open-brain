"""Intent classification and fuzzy matching for voice commands.

Pure Python, no I/O except the DB fetch in `match_open_todo`. The classifier
runs in microseconds and is deterministic — it never falls back to an LLM for
routing. The LLM is only invoked *after* an intent is locked in, to extract
structured fields (see src/llm/voice_extractor.py).
"""

from __future__ import annotations

import difflib
import re
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import TodoItem

Intent = Literal["create", "complete", "memory"]

# Prefixes that deterministically mark a create intent. Order matters only for
# logging; matching is set-based.
CREATE_PREFIXES: tuple[str, ...] = (
    "todo ",
    "task ",
    "remind me to ",
    "create a todo ",
    "create todo ",
    "new todo ",
    "add a todo ",
    "add todo ",
)

# Multi-word completion phrases checked before single verbs so "mark done"
# wins over a stray "done".
COMPLETE_PHRASES: tuple[str, ...] = (
    "mark done",
    "mark as done",
    "marked done",
)

COMPLETE_VERBS: frozenset[str] = frozenset(
    {
        "close",
        "closed",
        "complete",
        "completed",
        "done",
        "finish",
        "finished",
    }
)

# Noun markers that confirm the completion verb refers to a todo. The
# classifier requires BOTH a verb and one of these tokens before firing
# "complete" — bare "done" on its own falls through to memory.
TODO_NOUN_MARKERS: frozenset[str] = frozenset({"todo", "task", "the"})


_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_STRIP_RE = re.compile(r"^[\s\.,!\?;:]+|[\s\.,!\?;:]+$")


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip outer punctuation."""
    if not text:
        return ""
    stripped = _PUNCT_STRIP_RE.sub("", text)
    collapsed = _WHITESPACE_RE.sub(" ", stripped)
    return collapsed.lower().strip()


def classify_intent(text: str) -> Intent:
    """Classify dictation into create | complete | memory.

    Rules (first match wins):
        1. Normalize the text (lowercase, collapse whitespace, strip outer
           punctuation).
        2. If it starts with any CREATE_PREFIXES → "create". This makes
           "remind me to close the fridge" resolve as create even though
           "close" appears inside the sentence.
        3. If it contains any COMPLETE_PHRASES or a COMPLETE_VERBS token AND
           a TODO_NOUN_MARKERS token → "complete".
        4. Otherwise → "memory".

    An empty or whitespace-only string classifies as "memory" — the route
    layer rejects those at the pydantic validation step before reaching this
    function, so this is a safety net.
    """
    normalized = _normalize(text)
    if not normalized:
        return "memory"

    for prefix in CREATE_PREFIXES:
        # Require the trigger token AND something after it — a bare "todo"
        # on its own is too short to form a real create command.
        if normalized.startswith(prefix):
            return "create"

    # Phrase-level completion markers (multi-word)
    if any(phrase in normalized for phrase in COMPLETE_PHRASES):
        return "complete"

    tokens = set(normalized.split())
    has_verb = bool(tokens & COMPLETE_VERBS)
    has_noun = bool(tokens & TODO_NOUN_MARKERS)
    if has_verb and has_noun:
        return "complete"

    return "memory"


# ── Fuzzy matching ────────────────────────────────────────────────────────────

# Minimum score for a match to be considered "confident". Tuned for
# dictation drift (typos, partial phrases) without letting near-unrelated
# todos slip through. See tests/test_voice_command.py for the matrix.
MATCH_CONFIDENCE_THRESHOLD: float = 0.70

# If the top two candidates are within this score margin, we treat the
# result as ambiguous (tie-break).
MATCH_TIE_MARGIN: float = 0.05

# Upper bound on how many open todos we score. Dozens is the realistic
# working set; 200 is a hard ceiling to keep total fuzzy-match work under
# ~20ms even if the user has a hoarded backlog.
_CANDIDATE_LIMIT: int = 200


def _score(a: str, b: str) -> float:
    """Normalized SequenceMatcher ratio on whitespace-collapsed lowercase."""
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


async def match_open_todo(
    session: AsyncSession,
    target_phrase: str,
) -> tuple[TodoItem | None, float]:
    """Fuzzy-match `target_phrase` against open todo descriptions.

    Returns a `(todo, score)` tuple. Returns `(None, score)` when:
      - there are no open todos (score=0.0)
      - no candidate clears `MATCH_CONFIDENCE_THRESHOLD`
      - the top two candidates are within `MATCH_TIE_MARGIN` of each other

    The caller should treat `todo is None` as "ambiguous" and emit a no-op
    response — never mutate state on a sub-threshold match.
    """
    target = _normalize(target_phrase)
    if not target:
        return (None, 0.0)

    result = await session.execute(
        select(TodoItem)
        .where(TodoItem.status == "open")
        .order_by(TodoItem.created_at.desc())
        .limit(_CANDIDATE_LIMIT)
    )
    candidates = list(result.scalars().all())
    if not candidates:
        return (None, 0.0)

    scored: list[tuple[float, TodoItem]] = [
        (_score(target_phrase, todo.description), todo) for todo in candidates
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    top_score, top_todo = scored[0]

    if top_score < MATCH_CONFIDENCE_THRESHOLD:
        return (None, top_score)

    # Tie-break: if the runner-up is within the margin, treat as ambiguous.
    if len(scored) > 1:
        runner_up_score = scored[1][0]
        if top_score - runner_up_score < MATCH_TIE_MARGIN:
            return (None, top_score)

    return (top_todo, top_score)
