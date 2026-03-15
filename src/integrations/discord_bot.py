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
from typing import Any

import discord
import httpx
import structlog
from discord import app_commands

logger = structlog.get_logger()


def _get_settings() -> Any:
    """Lazy-load settings singleton (mirrors pattern in auth.py / ranking.py)."""
    from src.core import config

    if config.settings is None:
        config.settings = config.Settings()
    return config.settings


# ── Pure business-logic helpers (testable without Discord objects) ─────────────


async def ingest_memory(
    http: httpx.AsyncClient,
    raw_text: str,
    author_id: str,
    channel_id: str,
    api_key: str,
    api_base_url: str,
) -> str:
    """POST /v1/memory and return the raw_id string.

    Raises:
        httpx.HTTPStatusError: if the API returns a non-2xx status.
    """
    response = await http.post(
        f"{api_base_url}/v1/memory",
        json={
            "source": "discord",
            "text": raw_text,
            "metadata": {"channel_id": channel_id, "author_id": author_id},
        },
        headers={"X-API-Key": api_key},
    )
    response.raise_for_status()
    return str(response.json()["raw_id"])


async def search_memories(
    http: httpx.AsyncClient,
    query: str,
    limit: int,
    api_key: str,
    api_base_url: str,
) -> list[dict[str, Any]]:
    """GET /v1/search and return the results list.

    Raises:
        httpx.HTTPStatusError: if the API returns a non-2xx status.
    """
    response = await http.get(
        f"{api_base_url}/v1/search",
        params={"q": query, "limit": limit},
        headers={"X-API-Key": api_key},
    )
    response.raise_for_status()
    data = response.json()
    # API returns {"results": [...]} wrapper
    if isinstance(data, dict):
        return list(data.get("results", []))
    return list(data)  # type: ignore[no-any-return]


async def get_api_health(
    http: httpx.AsyncClient,
    api_base_url: str,
) -> bool:
    """Return True if the API /ready endpoint returns 200."""
    try:
        response = await http.get(f"{api_base_url}/ready")
        return response.status_code == 200
    except httpx.RequestError:
        return False


# ── Bot ────────────────────────────────────────────────────────────────────────


class OpenBrainBot(discord.Client):
    """Discord bot that captures memories and exposes search via slash commands."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # privileged intent — enable in dev portal
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._http = http_client
        self._register_commands()

    def _register_commands(self) -> None:
        """Register slash commands on the command tree."""

        @self.tree.command(name="search", description="Search your Open Brain memories")
        @app_commands.describe(query="What to search for")
        async def search_cmd(interaction: discord.Interaction, query: str) -> None:
            settings = _get_settings()
            if interaction.user.id not in settings.discord_allowed_user_ids:
                await interaction.response.send_message("Not authorised.", ephemeral=True)
                return

            await interaction.response.defer()

            try:
                results = await search_memories(
                    self._http,
                    query,
                    limit=5,
                    api_key=settings.api_key,
                    api_base_url=settings.open_brain_api_url,
                )
            except httpx.HTTPStatusError as exc:
                logger.error("discord_search_error", status=exc.response.status_code)
                await interaction.followup.send("Search failed — API error.", ephemeral=True)
                return

            if not results:
                await interaction.followup.send(f'No memories found for **"{query}"**.')
                return

            try:
                embed = discord.Embed(
                    title=f'Search: "{query}"',
                    color=discord.Color.blurple(),
                )
                for i, item in enumerate(results, 1):
                    content = item.get("content", "")
                    preview = content[:200] + "…" if len(content) > 200 else content
                    score = item.get("combined_score", item.get("score", 0))
                    embed.add_field(
                        name=f"#{i} · score {score:.3f}",
                        value=preview or "*(empty)*",
                        inline=False,
                    )
                await interaction.followup.send(embed=embed)
            except Exception as exc:
                logger.error("discord_search_reply_error", error=str(exc))
                await interaction.followup.send("Search succeeded but failed to format results.", ephemeral=True)

        @self.tree.command(name="status", description="Show Open Brain pipeline status")
        async def status_cmd(interaction: discord.Interaction) -> None:
            settings = _get_settings()
            if interaction.user.id not in settings.discord_allowed_user_ids:
                await interaction.response.send_message("Not authorised.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            healthy = await get_api_health(self._http, settings.open_brain_api_url)
            status_line = "✅ API online" if healthy else "❌ API unreachable"
            await interaction.followup.send(status_line, ephemeral=True)

    async def setup_hook(self) -> None:
        """Sync slash commands after login."""
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

        log = logger.bind(author_id=message.author.id, channel_id=message.channel.id)

        try:
            raw_id = await ingest_memory(
                self._http,
                raw_text=raw_text,
                author_id=str(message.author.id),
                channel_id=str(message.channel.id),
                api_key=settings.api_key,
                api_base_url=settings.open_brain_api_url,
            )
            log.info("discord_memory_ingested", raw_id=raw_id)
            await message.add_reaction("🧠")
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
