"""Discord interactive handler for Morning Pulse.

Provides a persistent View (Log / Skip buttons) attached to the morning pulse
embed, and a Modal for structured input. The free-text DM reply flow is kept
as a gated fallback (disabled by default).

Flow:
    Cron sends embed with components (pulse:log, pulse:skip custom_ids)
    → User clicks "Log my morning" → PulseModal opens
    → Modal submit → validate → PATCH /v1/pulse/today → react ✅
    OR
    → User clicks "Skip" → PATCH status=skipped → react ⏭️
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import discord
import httpx
import structlog

from src.integrations.kernel import _get_settings

logger = structlog.get_logger(__name__)

# Module-level references set by register_pulse
_pulse_cog_instance: PulseCog | None = None
_http_client: httpx.AsyncClient | None = None


# ── API helpers ───────────────────────────────────────────────────────────────


async def _get_today_pulse_api(settings: Any) -> dict[str, Any] | None:
    """GET /v1/pulse/today — returns pulse dict or None."""
    if _http_client is None:
        return None
    try:
        resp = await _http_client.get(
            f"{settings.open_brain_api_url}/v1/pulse/today",
            headers={"X-API-Key": settings.api_key.get_secret_value()},
        )
    except httpx.RequestError:
        logger.exception("pulse_cog_get_today_failed")
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


async def _patch_pulse_api(settings: Any, body: dict[str, Any]) -> bool:
    """PATCH /v1/pulse/today. Returns True on success."""
    if _http_client is None:
        return False
    try:
        resp = await _http_client.patch(
            f"{settings.open_brain_api_url}/v1/pulse/today",
            json=body,
            headers={"X-API-Key": settings.api_key.get_secret_value()},
        )
        return resp.status_code == 200
    except httpx.RequestError:
        logger.exception("pulse_cog_patch_failed", body_keys=list(body.keys()))
        return False


# ── Modal ─────────────────────────────────────────────────────────────────────


class PulseModal(discord.ui.Modal, title="Log my morning"):
    """Structured morning check-in modal.

    Fields (in order):
      1. Sleep quality (1-5, required)
      2. Energy level (1-5, required)
      3. Wake time (HH:MM, optional)
      4. AI question response (dynamic label, optional — omitted if no question)
      5. Notes / mood (optional)
    """

    sleep_quality = discord.ui.TextInput(
        label="Sleep quality (1-5)",
        placeholder="1-5",
        required=True,
        max_length=1,
    )
    energy_level = discord.ui.TextInput(
        label="Energy level (1-5)",
        placeholder="1-5",
        required=True,
        max_length=1,
    )
    wake_time = discord.ui.TextInput(
        label="Wake time",
        placeholder="HH:MM",
        required=False,
        max_length=5,
    )

    def __init__(self, ai_question: str = "", original_message: discord.Message | None = None) -> None:
        super().__init__()
        self._ai_question = ai_question
        self._original_message = original_message

        # Field 4: AI question response (label depends on whether the signal is a
        # question or a remark; absent if the pulse has no ai_question — e.g.
        # silent days would never render a modal in the first place).
        if ai_question:
            label = "Your answer" if ai_question.rstrip().endswith("?") else "Thoughts?"
            self.ai_response = discord.ui.TextInput(
                label=label,
                required=False,
                style=discord.TextStyle.paragraph,
                max_length=500,
            )
            self.add_item(self.ai_response)
        else:
            self.ai_response = None

        # Field 5: Notes / mood (always present)
        self.notes_field = discord.ui.TextInput(
            label="Notes / mood",
            placeholder="anything else on your mind",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.add_item(self.notes_field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Validate, store, react, disable buttons."""
        settings = _get_settings()

        # ── Double-submit check ───────────────────────────────────────────────
        pulse = await _get_today_pulse_api(settings)
        if pulse is None or pulse.get("status") in ("completed", "skipped"):
            await interaction.response.send_message(
                "Already logged or skipped today's pulse.", ephemeral=True,
            )
            return

        # ── Validate sleep quality ────────────────────────────────────────────
        try:
            sleep = int(str(self.sleep_quality))
            if not 1 <= sleep <= 5:
                raise ValueError
        except (ValueError, TypeError):
            await interaction.response.send_message(
                "Sleep quality must be a number 1-5.", ephemeral=True,
            )
            return

        # ── Validate energy level ─────────────────────────────────────────────
        try:
            energy = int(str(self.energy_level))
            if not 1 <= energy <= 5:
                raise ValueError
        except (ValueError, TypeError):
            await interaction.response.send_message(
                "Energy level must be a number 1-5.", ephemeral=True,
            )
            return

        # ── Parse wake time (flexible: HH:MM, H:MM) ──────────────────────────
        raw_wake = str(self.wake_time).strip() if self.wake_time else ""
        wake: str | None = None
        if raw_wake:
            match = re.match(r"^(\d{1,2}):(\d{2})$", raw_wake)
            if match:
                h, m = int(match.group(1)), int(match.group(2))
                if 0 <= h <= 23 and 0 <= m <= 59:
                    wake = f"{h:02d}:{m:02d}"

        # ── Collect text fields ───────────────────────────────────────────────
        ai_response_text = str(self.ai_response).strip() if self.ai_response else ""
        notes_text = str(self.notes_field).strip() if self.notes_field else ""

        # Combine into notes (AI response + free notes)
        combined_notes_parts: list[str] = []
        if ai_response_text:
            combined_notes_parts.append(ai_response_text)
        if notes_text:
            combined_notes_parts.append(notes_text)
        combined_notes = "\n\n".join(combined_notes_parts) if combined_notes_parts else None

        # ── Build raw_response JSON for audit ─────────────────────────────────
        raw_response = json.dumps({
            "sleep_quality": sleep,
            "energy_level": energy,
            "wake_time": wake,
            "ai_question": self._ai_question,
            "ai_question_response": ai_response_text or None,
            "notes": notes_text or None,
        })

        # ── PATCH the pulse ───────────────────────────────────────────────────
        body: dict[str, Any] = {
            "sleep_quality": sleep,
            "energy_level": energy,
            "status": "completed",
            "raw_reply": raw_response,
        }
        if wake:
            body["wake_time"] = wake
        if ai_response_text:
            body["ai_question_response"] = ai_response_text
        if combined_notes:
            body["notes"] = combined_notes

        await _patch_pulse_api(settings, body)

        # ── Disable buttons on original message ──────────────────────────────
        if self._original_message is not None:
            try:
                disabled_view = PulseView()
                for item in disabled_view.children:
                    item.disabled = True  # type: ignore[union-attr]
                await self._original_message.edit(view=disabled_view)
            except discord.HTTPException:
                logger.warning("pulse_modal_disable_buttons_failed")

            try:
                await self._original_message.add_reaction("✅")
            except discord.HTTPException:
                logger.warning("pulse_modal_react_failed")

        # ── Ephemeral confirmation ────────────────────────────────────────────
        await interaction.response.send_message(
            f"Logged. Sleep {sleep}, Energy {energy}. Have a good day.",
            ephemeral=True,
        )
        logger.info("pulse_modal_submitted", sleep=sleep, energy=energy)


# ── Persistent View ───────────────────────────────────────────────────────────


class PulseView(discord.ui.View):
    """Persistent view attached to the morning pulse embed.

    Buttons:
      - "Log my morning" (primary) → opens PulseModal
      - "Skip" (secondary) → marks pulse as skipped

    timeout=None + explicit custom_ids make this survive bot restarts.
    Must be re-registered via bot.add_view() in setup_hook / register_pulse.
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Log my morning",
        style=discord.ButtonStyle.primary,
        custom_id="pulse:log",
    )
    async def log_button(
        self, interaction: discord.Interaction, button: discord.ui.Button,
    ) -> None:
        """Open the pulse modal with today's AI question as a dynamic field label."""
        settings = _get_settings()
        pulse = await _get_today_pulse_api(settings)

        if pulse is None:
            await interaction.response.send_message(
                "No active pulse found for today.", ephemeral=True,
            )
            return

        if pulse.get("status") in ("completed", "skipped"):
            await interaction.response.send_message(
                "Already logged or skipped today's pulse.", ephemeral=True,
            )
            return

        ai_question = pulse.get("ai_question", "")
        modal = PulseModal(
            ai_question=ai_question or "",
            original_message=interaction.message,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Skip",
        style=discord.ButtonStyle.secondary,
        custom_id="pulse:skip",
    )
    async def skip_button(
        self, interaction: discord.Interaction, button: discord.ui.Button,
    ) -> None:
        """Mark today's pulse as skipped and disable buttons."""
        settings = _get_settings()

        pulse = await _get_today_pulse_api(settings)
        if pulse is None:
            await interaction.response.send_message(
                "No active pulse found for today.", ephemeral=True,
            )
            return

        if pulse.get("status") in ("completed", "skipped"):
            await interaction.response.send_message(
                "Already logged or skipped today's pulse.", ephemeral=True,
            )
            return

        await _patch_pulse_api(settings, {"status": "skipped"})

        # Disable buttons
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(view=self)

        try:
            if interaction.message is not None:
                await interaction.message.add_reaction("⏭️")
        except discord.HTTPException:
            logger.warning("pulse_skip_react_failed")

        await interaction.followup.send("⏭️ Skipped.", ephemeral=True)
        logger.info("pulse_skipped")


# ── Pure helpers (kept for free-text fallback) ────────────────────────────────


def _is_within_reply_window(pulse_created_at: datetime, window_minutes: int) -> bool:
    """Return True if now is within window_minutes of pulse_created_at."""
    now = datetime.now(UTC)
    if pulse_created_at.tzinfo is None:
        pulse_created_at = pulse_created_at.replace(tzinfo=UTC)
    elapsed = (now - pulse_created_at).total_seconds() / 60
    return elapsed < window_minutes


def _build_confirmation_embed(parsed: dict[str, Any], raw_reply: str) -> discord.Embed:
    """Build a confirmation embed shown after a pulse reply is processed."""
    sleep = parsed.get("sleep_quality")
    energy = parsed.get("energy_level")
    wake = parsed.get("wake_time")
    note = parsed.get("mood_note")

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


# ── Cog class (free-text fallback, gated) ─────────────────────────────────────


class PulseCog:
    """Handles Discord DM replies to the morning pulse (free-text fallback)."""

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
        """Check if this DM is a pulse reply and handle it (free-text path).

        Only active when pulse_accept_freetext is True in settings.

        Returns:
            True if handled, False otherwise.
        """
        settings = _get_settings()

        # Gate: free-text path disabled by default
        if not getattr(settings, "pulse_accept_freetext", False):
            return False

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
    """Attach the PulseCog and persistent PulseView to the bot.

    Called from discord_bot.setup_hook(). Sets module-level references so
    View/Modal callbacks can access the HTTP client and settings.

    Args:
        bot: The Discord client.
        http: Shared httpx.AsyncClient.
        settings: Open Brain settings.
    """
    global _pulse_cog_instance, _http_client

    if not settings.module_pulse_enabled:
        return

    _pulse_cog_instance = PulseCog(http)
    _http_client = http

    # Register persistent view so buttons survive bot restarts
    bot.add_view(PulseView())

    logger.info("pulse_cog_registered")
