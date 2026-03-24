"""Core Discord slash commands: /search, /digest, /status.

Extracted from discord_bot.py to keep the main bot loader thin.
All commands use the shared kernel helpers.
"""

from typing import Any

import discord
import httpx
import structlog
from discord import app_commands

from src.integrations.kernel import (
    _get_settings,
    get_api_health,
    require_allowed_user,
    search_memories,
    trigger_digest,
)

logger = structlog.get_logger()


def register_core(tree: app_commands.CommandTree, http: httpx.AsyncClient) -> None:
    """Register /search, /digest, /status on the command tree."""

    @tree.command(name="search", description="Search your Open Brain memories")
    @app_commands.describe(query="What to search for")
    async def search_cmd(interaction: discord.Interaction, query: str) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            results = await search_memories(
                http,
                query,
                limit=5,
                api_key=settings.api_key.get_secret_value(),
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
            await interaction.followup.send(
                "Search succeeded but failed to format results.", ephemeral=True
            )

    @tree.command(name="digest", description="Run weekly synthesis digest")
    @app_commands.describe(days="Number of days to synthesize (default: 7, max: 90)")
    async def digest_cmd(interaction: discord.Interaction, days: int = 7) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return

        if not 1 <= days <= 90:
            await interaction.response.send_message(
                "days must be between 1 and 90.", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            result = await trigger_digest(
                http,
                days=days,
                api_key=settings.api_key.get_secret_value(),
                api_base_url=settings.open_brain_api_url,
            )
        except httpx.HTTPStatusError as exc:
            logger.error("discord_digest_error", status=exc.response.status_code)
            await interaction.followup.send("Digest failed — API error.", ephemeral=True)
            return
        except httpx.RequestError as exc:
            logger.error("discord_digest_request_error", error=str(exc))
            await interaction.followup.send(
                "Digest failed — could not reach API.", ephemeral=True
            )
            return

        if result.get("skipped"):
            await interaction.followup.send(
                f"No memories found in the last {days} day(s). Nothing to synthesize."
            )
            return

        try:
            embed = discord.Embed(
                title=f"Weekly Digest ({result['date_from']} → {result['date_to']})",
                color=discord.Color.green(),
            )
            embed.add_field(name="Memories processed", value=str(result["memory_count"]), inline=True)
            sid = result.get("synthesis_id") or "N/A"
            embed.add_field(
                name="Report ID", value=sid[:8] + "…" if len(sid) > 8 else sid, inline=True
            )
            embed.set_footer(text=result.get("message", "Synthesis complete"))
            await interaction.followup.send(embed=embed)
        except Exception as exc:
            logger.error("discord_digest_reply_error", error=str(exc))
            await interaction.followup.send(
                "Digest succeeded but failed to format response.", ephemeral=True
            )

    @tree.command(name="status", description="Show Open Brain pipeline status")
    async def status_cmd(interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        healthy = await get_api_health(http, settings.open_brain_api_url)
        status_line = "✅ API online" if healthy else "❌ API unreachable"
        await interaction.followup.send(status_line, ephemeral=True)
