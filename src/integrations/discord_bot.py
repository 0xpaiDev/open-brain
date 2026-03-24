"""Discord bot integration for Open Brain.

Any plain-text DM or channel message from an allowed user is ingested as a memory.
Slash commands provide search and status.

Setup:
    1. Create an application at https://discord.com/developers/applications
    2. Add a Bot, copy the token → DISCORD_BOT_TOKEN in .env
    3. Enable "Message Content Intent" under Bot → Privileged Gateway Intents
    4. Invite the bot to a private server (or use DMs)
    5. Set DISCORD_ALLOWED_USER_IDS=<your-discord-user-id> in .env

Run:
    python -m src.integrations.discord_bot
"""

import asyncio

import discord
import httpx
import structlog
from discord import app_commands

# Re-export pure helpers so existing imports from this module continue to work
from src.integrations.kernel import (
    _get_settings,
    get_api_health,
    ingest_memory,
    require_allowed_user,
    search_memories,
    trigger_digest,
)

logger = structlog.get_logger()

__all__ = [
    "_get_settings",
    "ingest_memory",
    "search_memories",
    "trigger_digest",
    "get_api_health",
    "require_allowed_user",
    "OpenBrainBot",
]


# ── Bot ────────────────────────────────────────────────────────────────────────


class OpenBrainBot(discord.Client):
    """Discord bot that captures memories and exposes search via slash commands."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # privileged intent — enable in dev portal
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._http = http_client

    async def setup_hook(self) -> None:
        """Load module cogs and sync slash commands after login."""
        from src.core.database import init_db
        from src.integrations.modules.core_cog import register_core

        await init_db()
        register_core(self.tree, self._http)

        settings = _get_settings()

        if settings.module_todo_enabled:
            from src.integrations.modules.todo_cog import TodoGroup

            self.tree.add_command(TodoGroup(self._http))

        if settings.module_rag_chat_enabled:
            from src.integrations.modules.rag_cog import register_rag  # type: ignore[import]

            register_rag(self, self._http, settings)

        if settings.module_pulse_enabled:
            from src.integrations.modules.pulse_cog import register_pulse  # type: ignore[import]

            register_pulse(self, self._http, settings)

        synced = await self.tree.sync()
        logger.info("discord_commands_synced", count=len(synced))

    async def on_ready(self) -> None:
        logger.info("discord_bot_ready", username=str(self.user))

    async def on_message(self, message: discord.Message) -> None:
        """Ingest any plain-text message from an allowed user."""
        if message.author == self.user:
            return  # ignore own messages

        settings = _get_settings()
        if message.author.id not in settings.discord_allowed_user_ids:
            return  # silently ignore unauthorised users

        raw_text = message.content.strip()
        if not raw_text:
            return  # ignore empty / attachment-only messages

        # RAG handler owns messages with the trigger prefix in RAG channels
        if (
            settings.module_rag_chat_enabled
            and message.channel.id in settings.discord_rag_channel_ids
            and raw_text.startswith(settings.rag_trigger_prefix)
        ):
            from src.integrations.modules.rag_cog import _rag_handler

            if _rag_handler is not None:
                await _rag_handler(message)
            return

        # Skip: Pulse handler owns DM replies from the configured pulse user
        if (
            settings.module_pulse_enabled
            and settings.discord_pulse_user_id != 0
            and message.author.id == settings.discord_pulse_user_id
            and message.channel.type == discord.ChannelType.private
        ):
            from src.integrations.modules.pulse_cog import _pulse_cog_instance

            if _pulse_cog_instance is not None:
                handled = await _pulse_cog_instance.handle_reply(message)
                if handled:
                    return

        log = logger.bind(author_id=message.author.id, channel_id=message.channel.id)

        try:
            raw_id, ingest_status = await ingest_memory(
                self._http,
                raw_text=raw_text,
                author_id=str(message.author.id),
                channel_id=str(message.channel.id),
                api_key=settings.api_key.get_secret_value(),
                api_base_url=settings.open_brain_api_url,
            )
            log.info("discord_memory_ingested", raw_id=raw_id, status=ingest_status)
            if ingest_status == "duplicate":
                await message.add_reaction("♻️")  # already in memory, not re-queued
            else:
                await message.add_reaction("🧠")  # newly queued for processing
        except httpx.HTTPStatusError as exc:
            log.error("discord_ingest_error", status=exc.response.status_code)
            await message.add_reaction("❌")
        except httpx.RequestError as exc:
            log.error("discord_ingest_request_error", error=str(exc))
            await message.add_reaction("❌")


# ── Entry point ────────────────────────────────────────────────────────────────


async def main() -> None:
    """Start the Discord bot. Reads config from environment / .env."""
    settings = _get_settings()
    token = settings.discord_bot_token.get_secret_value()

    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set. Add it to .env or the environment.")

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        bot = OpenBrainBot(http_client)
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
