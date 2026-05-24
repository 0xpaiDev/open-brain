"""Agentic tool-use loop for chat tool calls."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.llm.client import anthropic_client
from src.observability import record_tool_call, start_step
from src.observability.rerun import register_rerun_handler

logger = structlog.get_logger(__name__)

MAX_ITERATIONS = 10


class ToolError(Exception):
    """Raised by tool handlers to surface a user-visible error to the model."""


async def run_tool_loop(
    *,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    model: str,
    max_tokens: int,
    session: AsyncSession,
    user_id: uuid.UUID,
    dispatch: Callable,
    user_message: str,
    tools_enabled: bool,
    intent_tool: str | None,
    intent_method: str | None,
) -> str:
    start_ms = int(time.time() * 1000)
    loop_messages = list(messages)
    llm_calls: list[dict] = []
    tool_calls_log: list[dict] = []

    for iteration in range(MAX_ITERATIONS):
        async with start_step(f"tool_loop_iter_{iteration}"):
            raw = await anthropic_client._messages_create(
                messages=loop_messages,
                system=system_prompt,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
            )

            llm_calls.append(
                {
                    "turn_index": iteration,
                    "model": model,
                    "stop_reason": raw.stop_reason,
                    "input_message_count": len(loop_messages),
                }
            )

            if raw.stop_reason == "end_turn":
                text = next((b.text for b in raw.content if b.type == "text"), "")
                await _write_log(
                    session=session,
                    user_message=user_message,
                    tools_enabled=tools_enabled,
                    intent_tool=intent_tool,
                    intent_method=intent_method,
                    llm_calls=llm_calls,
                    tool_calls=tool_calls_log,
                    response_text=text,
                    model_used=model,
                    duration_ms=int(time.time() * 1000) - start_ms,
                )
                return text

            tool_use_blocks = [b for b in raw.content if b.type == "tool_use"]
            tool_result_content: list[dict] = []

            for block in tool_use_blocks:
                t_start = int(time.time() * 1000)
                t_start_dt = datetime.now(UTC)
                try:
                    result_text = await dispatch(block.name, block.input, session, user_id)
                    is_error = False
                except ToolError as exc:
                    result_text = str(exc)
                    is_error = True
                except Exception as exc:
                    logger.warning(
                        "tool_dispatch_unexpected_error", tool=block.name, error=str(exc)
                    )
                    result_text = f"Tool error: {exc}"
                    is_error = True

                t_end_dt = datetime.now(UTC)

                tool_calls_log.append(
                    {
                        "tool_name": block.name,
                        "args": block.input,
                        "result": result_text,
                        "duration_ms": int(time.time() * 1000) - t_start,
                        "is_error": is_error,
                    }
                )
                tool_result_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )

                await record_tool_call(
                    tool_name=block.name,
                    args=block.input if isinstance(block.input, dict) else {},
                    status="error" if is_error else "success",
                    result={"text": result_text[:500]} if result_text else None,
                    is_error=is_error,
                    error_message=result_text if is_error else None,
                    started_at=t_start_dt,
                    finished_at=t_end_dt,
                )

            loop_messages.append({"role": "assistant", "content": raw.content})
            loop_messages.append({"role": "user", "content": tool_result_content})

    cap_msg = "I wasn't able to complete that in one turn."
    await _write_log(
        session=session,
        user_message=user_message,
        tools_enabled=tools_enabled,
        intent_tool=intent_tool,
        intent_method=intent_method,
        llm_calls=llm_calls,
        tool_calls=tool_calls_log,
        response_text=cap_msg,
        model_used=model,
        duration_ms=int(time.time() * 1000) - start_ms,
    )
    return cap_msg


async def _write_log(
    *,
    session: AsyncSession,
    user_message: str,
    tools_enabled: bool,
    intent_tool: str | None,
    intent_method: str | None,
    llm_calls: list[dict],
    tool_calls: list[dict],
    response_text: str,
    model_used: str,
    duration_ms: int,
) -> None:
    try:
        from src.core.models import ChatLog

        log = ChatLog(
            user_message=user_message,
            tools_enabled=tools_enabled,
            intent_tool=intent_tool,
            intent_method=intent_method,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            response_text=response_text,
            model_used=model_used,
            duration_ms=duration_ms,
        )
        session.add(log)
        await session.commit()
    except Exception:
        logger.warning("chat_log_write_failed", exc_info=True)


async def _handle_chat_rerun(trace) -> None:
    # Chat reruns require live session + user context — not supported for automatic rerun.
    raise NotImplementedError("Chat reruns must be triggered via the chat API endpoint")


register_rerun_handler("http", _handle_chat_rerun)
