"""Migration 0014 sanity: signal_type column on daily_pulse."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.core.models import DailyPulse


@pytest.mark.asyncio
async def test_daily_pulse_has_signal_type_column(async_session):
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 23, tzinfo=UTC),
        status="sent",
        ai_question="Q?",
        signal_type="focus",
    )
    async_session.add(pulse)
    await async_session.commit()
    await async_session.refresh(pulse)

    row = (await async_session.execute(select(DailyPulse).where(DailyPulse.id == pulse.id))).scalar_one()
    assert row.signal_type == "focus"


@pytest.mark.asyncio
async def test_daily_pulse_signal_type_nullable(async_session):
    pulse = DailyPulse(
        pulse_date=datetime(2026, 4, 23, tzinfo=UTC),
        status="sent",
        ai_question="Q?",
    )
    async_session.add(pulse)
    await async_session.commit()
    await async_session.refresh(pulse)

    assert pulse.signal_type is None
