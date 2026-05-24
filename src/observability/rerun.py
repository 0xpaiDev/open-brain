"""Rerun handler registry.

Handlers are registered per trigger_type by Phase 2 instrumentation.
dispatch_rerun() opens a new Trace with rerun_of_trace_id set and
invokes the appropriate handler.

Usage (Phase 2, in runner.py):
    from src.observability.rerun import register_rerun_handler

    async def _handle_cron_rerun(trace, session):
        job_fn = JOB_REGISTRY[trace.trigger_name]
        await job_fn()

    register_rerun_handler("cron", _handle_cron_rerun)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.core.models import Trace

log = structlog.get_logger(__name__)

RerunHandler = Callable[["Trace"], Awaitable[str]]

_handlers: dict[str, RerunHandler] = {}


def register_rerun_handler(trigger_type: str, handler: RerunHandler) -> None:
    """Register a rerun handler for a trigger_type. Last write wins."""
    _handlers[trigger_type] = handler


async def dispatch_rerun(trace: Trace) -> str:
    """Open a new trace with rerun_of_trace_id set and invoke the handler.

    Returns the new trace_id. Raises ValueError if no handler registered.
    """
    from src.core.database import get_db_context
    from src.core.models import Trace as TraceModel
    from src.observability.context import start_trace

    handler = _handlers.get(trace.trigger_type)
    if handler is None:
        raise ValueError(
            f"No rerun handler registered for trigger_type={trace.trigger_type!r}. "
            f"Registered types: {list(_handlers)}"
        )

    new_trace_id: str | None = None

    async with start_trace(
        trigger_type="manual_rerun",
        trigger_name=trace.trigger_name,
        trigger_metadata=trace.trigger_metadata,
    ) as ctx:
        new_trace_id = str(ctx.trace_id)

        # Link the rerun to the original trace
        async with get_db_context() as link_session:
            new_trace_row = await link_session.get(TraceModel, ctx.trace_id)
            if new_trace_row:
                new_trace_row.rerun_of_trace_id = trace.id
                await link_session.commit()

        await handler(trace)

    return new_trace_id  # type: ignore[return-value]


def registered_trigger_types() -> list[str]:
    return list(_handlers)
