"""Daily learning-todo injection cron.

Each morning before pulse, select N items from active learning topics and
create real TodoItem rows with `learning_item_id` populated. These todos
render on /today with a subtle "Learning" badge and cascade back to the
underlying item on completion.

Idempotency: counts existing learning todos for today and only fills the
gap. Safe to re-run (also used by POST /v1/learning/refresh).

Fallback: when the LLM selector fails (timeout, non-JSON, zero valid items),
pick deterministically from oldest pending items across active topics.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.todo_service import create_todo
from src.core.config import get_settings
from src.core.database import get_db_context
from src.core.models import LearningItem, LearningSection, LearningTopic, TodoItem

logger = structlog.get_logger(__name__)

_MAX_SECTIONS_PER_TOPIC = 10
_MAX_ITEMS_PER_SECTION = 20
_MAX_FEEDBACK_ITEMS = 30


def _wrap(text: str | None) -> str:
    if text is None:
        return "<user_input></user_input>"
    safe = text.replace("</user_input>", "")
    return f"<user_input>{safe}</user_input>"


async def _count_todays_learning_todos(session: AsyncSession, today: date) -> int:
    start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    stmt = (
        select(func.count())
        .select_from(TodoItem)
        .where(
            TodoItem.learning_item_id.is_not(None),
            TodoItem.created_at >= start,
            TodoItem.created_at < end,
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def _existing_learning_item_ids_today(session: AsyncSession, today: date) -> set[str]:
    start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    stmt = select(TodoItem.learning_item_id).where(
        TodoItem.learning_item_id.is_not(None),
        TodoItem.created_at >= start,
        TodoItem.created_at < end,
    )
    result = await session.execute(stmt)
    return {str(r) for r in result.scalars().all()}


async def _active_topics_with_pending(session: AsyncSession) -> list[LearningTopic]:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(LearningTopic)
        .where(LearningTopic.is_active.is_(True))
        .options(selectinload(LearningTopic.sections).selectinload(LearningSection.items))
        .order_by(LearningTopic.position, LearningTopic.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _recent_feedback(session: AsyncSession, lookback_days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    stmt = (
        select(LearningItem)
        .where(
            and_(
                LearningItem.status == "done",
                LearningItem.completed_at >= cutoff,
                LearningItem.feedback.is_not(None),
            )
        )
        .order_by(LearningItem.completed_at.desc())
        .limit(_MAX_FEEDBACK_ITEMS)
    )
    result = await session.execute(stmt)
    return [
        {"title": _wrap(i.title), "feedback": _wrap(i.feedback)}
        for i in result.scalars().all()
    ]


def _build_llm_payload(
    topics: list[LearningTopic],
    feedback: list[dict[str, Any]],
    target_count: int,
    today: date,
    excluded_ids: set[str],
) -> tuple[dict[str, Any], list[LearningItem]]:
    """Build the JSON payload for the LLM and return the filtered flat item list."""
    flat: list[LearningItem] = []
    payload_topics: list[dict[str, Any]] = []
    for topic in topics:
        sections: list[dict[str, Any]] = []
        for section in topic.sections[:_MAX_SECTIONS_PER_TOPIC]:
            pending = [
                i
                for i in section.items
                if i.status == "pending" and str(i.id) not in excluded_ids
            ][:_MAX_ITEMS_PER_SECTION]
            if not pending:
                continue
            flat.extend(pending)
            sections.append(
                {
                    "name": _wrap(section.name),
                    "pending_items": [
                        {"id": str(i.id), "title": _wrap(i.title)} for i in pending
                    ],
                }
            )
        if not sections:
            continue
        payload_topics.append(
            {
                "id": str(topic.id),
                "name": _wrap(topic.name),
                "depth": topic.depth,
                "sections": sections,
            }
        )
    payload = {
        "today": today.isoformat(),
        "target_count": target_count,
        "active_topics": payload_topics,
        "recent_feedback": feedback,
    }
    return payload, flat


async def _select_via_llm(
    payload: dict[str, Any],
    flat_items: list[LearningItem],
    target_count: int,
    today: date,
) -> list[LearningItem] | None:
    """Return ordered list of items selected by LLM, or None on any failure."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.info("learning_llm_skipped_no_api_key")
        return None
    try:
        from src.llm.client import AnthropicClient
        from src.llm.prompts import build_learning_selection_system_prompt

        client = AnthropicClient(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.anthropic_model,
        )
        system = build_learning_selection_system_prompt(today, target_count)
        user_message = json.dumps(payload, ensure_ascii=False)
        raw = await asyncio.wait_for(
            client.complete(system, user_message, max_tokens=1024),
            timeout=settings.learning_llm_timeout_seconds,
        )
    except Exception as exc:
        logger.warning("learning_llm_call_failed", error=str(exc))
        return None

    try:
        parsed = json.loads(raw)
        selections = parsed.get("selections", [])
        if not isinstance(selections, list):
            return None
        by_id = {str(i.id): i for i in flat_items}
        out: list[LearningItem] = []
        seen: set[str] = set()
        for sel in selections[:target_count]:
            if not isinstance(sel, dict):
                continue
            iid = str(sel.get("item_id", ""))
            if iid in seen or iid not in by_id:
                continue
            seen.add(iid)
            out.append(by_id[iid])
        if not out:
            return None
        return out
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _deterministic_fallback(
    flat_items: list[LearningItem],
    target_count: int,
) -> list[LearningItem]:
    """Stable fallback: oldest pending items first, tie-broken by id."""
    ordered = sorted(flat_items, key=lambda i: (i.created_at, str(i.id)))
    return ordered[:target_count]


async def _create_learning_todo(session: AsyncSession, item: LearningItem, today: date) -> TodoItem:
    """Create a TodoItem tied to this learning item.

    The description is seeded verbatim from the item title; importance stays
    "normal". The learning_item_id FK is what distinguishes these todos.
    """
    todo = await create_todo(
        session,
        description=item.title,
        priority="normal",
        due_date=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
        project="Learning",
    )
    todo.learning_item_id = item.id
    await session.commit()
    await session.refresh(todo)
    return todo


async def run_learning_selection(session: AsyncSession) -> dict[str, Any]:
    """Core logic — reused by cron and by POST /v1/learning/refresh.

    Returns a summary dict with counts and whether the fallback path was taken.
    """
    settings = get_settings()
    today = datetime.now(UTC).date()
    target = settings.learning_daily_todo_count

    if not settings.module_learning_enabled:
        logger.info("learning_cron_disabled")
        return {"created": 0, "skipped_existing": 0, "fallback": False, "target_count": target}

    existing_count = await _count_todays_learning_todos(session, today)
    if existing_count >= target:
        logger.info(
            "learning_cron_skipped_existing",
            existing=existing_count,
            target=target,
        )
        return {
            "created": 0,
            "skipped_existing": existing_count,
            "fallback": False,
            "target_count": target,
        }

    remaining = target - existing_count
    excluded = await _existing_learning_item_ids_today(session, today)
    topics = await _active_topics_with_pending(session)
    feedback = await _recent_feedback(session, settings.learning_feedback_lookback_days)
    payload, flat = _build_llm_payload(topics, feedback, remaining, today, excluded)

    if not flat:
        logger.info("learning_no_active_pending_items")
        return {
            "created": 0,
            "skipped_existing": existing_count,
            "fallback": False,
            "target_count": target,
        }

    selected = await _select_via_llm(payload, flat, remaining, today)
    fallback_used = False
    if selected is None:
        selected = _deterministic_fallback(flat, remaining)
        fallback_used = True

    created = 0
    for item in selected:
        try:
            await _create_learning_todo(session, item, today)
            created += 1
        except Exception:
            logger.warning("learning_todo_create_failed", item_id=str(item.id), exc_info=True)

    logger.info(
        "learning_cron_complete",
        created=created,
        skipped_existing=existing_count,
        fallback=fallback_used,
        target_count=target,
        feature_flag="on",
    )
    return {
        "created": created,
        "skipped_existing": existing_count,
        "fallback": fallback_used,
        "target_count": target,
    }


async def _learning_job() -> None:
    async with get_db_context() as session:
        await run_learning_selection(session)


async def main() -> None:
    from src.jobs.runner import run_tracked

    await run_tracked("learning_daily", _learning_job)


if __name__ == "__main__":
    asyncio.run(main())
