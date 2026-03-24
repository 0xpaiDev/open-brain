"""Discord DM handler for Morning Pulse replies.

Intercepts DM replies from the pulse user within the reply window,
parses them with Haiku, and updates the DailyPulse record via the REST API.

Flow:
    on_message (discord_bot.py) → guard fires → handle_reply()
    → GET /v1/pulse/today → window check
    → PATCH raw_reply → parse_pulse_reply → PATCH parsed fields
    → react 🌅 / ❓ → reply with confirmation embed
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import discord
import httpx
import structlog

from src.integrations.kernel import _get_settings

logger = structlog.get_logger(__name__)

# Module-level singleton set by register_pulse — referenced by discord_bot.py guard
_pulse_cog_instance: PulseCog | None = None


# ── Pure helpers ───────────────────────────────────────────────────────────────


def _is_within_reply_window(pulse_created_at: datetime, window_minutes: int) -> bool:
    """Return True if now is within window_minutes of pulse_created_at.

    Args:
        pulse_created_at: When the pulse was created (timezone-aware).
        window_minutes: Reply window in minutes.

    Returns:
        True if the current time is strictly before the window closes.
    """
    now = datetime.now(UTC)
    if pulse_created_at.tzinfo is None:
        pulse_created_at = pulse_created_at.replace(tzinfo=UTC)
    elapsed = (now - pulse_created_at).total_seconds() / 60
    return elapsed < window_minutes


def _build_confirmation_embed(parsed: dict[str, Any], raw_reply: str) -> discord.Embed:
    """Build a confirmation embed shown after a pulse reply is processed.

    Args:
        parsed: Parsed dict from Haiku (may be empty on parse failure).
        raw_reply: The user's original reply text.

    Returns:
        Discord Embed with extracted wellness data.
    """
    sleep = parsed.get("sleep_quality")
    energy = parsed.get("energy_level")
    wake = parsed.get("wake_time")
    note = parsed.get("mood_note")

    # Color based on energy level: green=high, yellow=medium, red=low, grey=unknown
    if energy is not None:
        color = discord.Color.green() if energy >= 4 else (discord.Color.gold() if energy >= 3 else discord.Color.red())
    else:
        color = discord.Color.light_grey()

    embed = discord.Embed(title="Morning Pulse — Logged", color=color)

    fields: list[tuple[str, str]] = []
    if sleep is not None:
        fields.append(("😴 Sleep", f"{sleep}/5"))
    if energy is not None:
        fields.append(("⚡ Energy", f"{energy}/5"))
    if wake:
        fields.append(("⏰ Wake time", wake))
    if note:
        fields.append(("📝 Note", note[:200]))

    if fields:
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
    else:
        embed.description = "Stored your reply — couldn't extract structured data."

    embed.set_footer(text="Open Brain · Morning Pulse")
    return embed


# ── Cog class ──────────────────────────────────────────────────────────────────


class PulseCog:
    """Handles Discord DM replies to the morning pulse."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def _get_pending_pulse(self, settings: Any) -> dict[str, Any] | None:
        """Return today's pulse dict if status="sent", else None."""
        try:
            resp = await self._http.get(
                f"{settings.open_brain_api_url}/v1/pulse/today",
                headers={"X-API-Key": settings.api_key.get_secret_value()},
            )
        except httpx.RequestError:
            logger.exception("pulse_cog_get_today_failed")
            return None
        if resp.status_code != 200:
            return None
        pulse = resp.json()
        return pulse if pulse.get("status") == "sent" else None

    async def _patch_pulse(self, settings: Any, body: dict[str, Any]) -> None:
        """PATCH /v1/pulse/today, logging on failure."""
        try:
            await self._http.patch(
                f"{settings.open_brain_api_url}/v1/pulse/today",
                json=body,
                headers={"X-API-Key": settings.api_key.get_secret_value()},
            )
        except httpx.RequestError:
            logger.exception("pulse_cog_patch_failed", body_keys=list(body.keys()))

    async def _parse_reply(self, raw_reply: str, settings: Any) -> dict[str, Any] | None:
        """Parse raw_reply with Haiku; return dict or None on failure."""
        from src.jobs.pulse import parse_pulse_reply

        llm = getattr(settings, "_llm_client", None) or _build_llm_client(settings)
        if llm is None:
            return None
        try:
            return await parse_pulse_reply(raw_reply, llm)
        except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError, ValueError) as exc:
            logger.exception("pulse_cog_parse_failed", error=str(exc))
            return None

    async def handle_reply(self, message: discord.Message) -> bool:
        """Check if this DM is a pulse reply and handle it.

        Args:
            message: Incoming Discord message.

        Returns:
            True if the message was handled as a pulse reply (caller should skip ingest).
            False if not a pulse reply (caller should proceed with normal handling).
        """
        settings = _get_settings()

        # 1. Check pending pulse
        pulse = await self._get_pending_pulse(settings)
        if pulse is None:
            return False

        # 2. Check reply window
        created_at_str = pulse.get("created_at", "")
        if created_at_str.endswith("Z"):
            created_at_str = created_at_str[:-1] + "+00:00"
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except (ValueError, TypeError):
            logger.warning("pulse_cog_invalid_created_at", created_at=pulse.get("created_at"))
            return False

        if not _is_within_reply_window(created_at, settings.pulse_reply_window_minutes):
            logger.info("pulse_cog_reply_window_expired")
            return False

        raw_reply = message.content.strip()
        logger.info("pulse_cog_reply_received", length=len(raw_reply))

        # 3. Store raw reply
        await self._patch_pulse(settings, {"raw_reply": raw_reply, "status": "replied"})

        # 4. Parse with Haiku
        parsed = await self._parse_reply(raw_reply, settings)

        # 5. Update with parsed data or mark parse_failed
        if parsed:
            update_body: dict[str, Any] = {"status": "parsed", "parsed_data": parsed}
            for key in ("sleep_quality", "energy_level", "wake_time"):
                if parsed.get(key) is not None:
                    update_body[key] = parsed[key]
            await self._patch_pulse(settings, update_body)
        else:
            await self._patch_pulse(settings, {"status": "parse_failed"})

        # 6. React and reply
        reaction = "🌅" if parsed else "❓"
        try:
            await message.add_reaction(reaction)
        except discord.HTTPException:
            logger.warning("pulse_cog_react_failed")

        try:
            embed = _build_confirmation_embed(parsed or {}, raw_reply)
            await message.reply(embed=embed)
        except discord.HTTPException:
            logger.warning("pulse_cog_reply_embed_failed")

        return True


# ── LLM client factory ─────────────────────────────────────────────────────────


def _build_llm_client(settings: Any) -> Any | None:
    """Construct AnthropicClient from settings, or None if token not configured."""
    try:
        from src.llm.client import AnthropicClient

        token = getattr(settings, "anthropic_api_key", None)
        if token is None:
            return None
        secret = token.get_secret_value() if hasattr(token, "get_secret_value") else str(token)
        if not secret:
            return None
        return AnthropicClient(api_key=secret)
    except (ImportError, ValueError, httpx.RequestError) as exc:
        logger.exception("pulse_cog_llm_client_build_failed", error=str(exc))
        return None


# ── Registration ───────────────────────────────────────────────────────────────


def register_pulse(bot: discord.Client, http: httpx.AsyncClient, settings: Any) -> None:
    """Attach the PulseCog to the bot. Called from discord_bot.setup_hook().

    Sets the module-level _pulse_cog_instance so the on_message guard
    in discord_bot.py can route DMs to it.

    Args:
        bot: The Discord client.
        http: Shared httpx.AsyncClient.
        settings: Open Brain settings.
    """
    global _pulse_cog_instance

    if not settings.module_pulse_enabled:
        return

    _pulse_cog_instance = PulseCog(http)
    logger.info("pulse_cog_registered")
