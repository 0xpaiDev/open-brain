"""Discord slash commands for the Todo module.

Provides /todo subcommand group with: list, add, done, defer.
Interactive embeds use discord.ui.View + Button + Modal for in-place updates.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import discord
import httpx
import structlog
from discord import app_commands

from src.integrations.kernel import _get_settings, require_allowed_user

logger = structlog.get_logger(__name__)


# ── Pure helpers ──────────────────────────────────────────────────────────────


def parse_natural_date(token: str, today: date) -> date | None:
    """Parse a natural-language date token (prefixed with @) into a date.

    Supported formats:
      @tomorrow          → today + 1 day
      @monday – @sunday  → next occurrence of that weekday (including today if it matches)
      @next-week         → Monday of the following week
      @YYYY-MM-DD        → exact ISO date

    Returns None if the token cannot be parsed.
    """
    if not token.startswith("@"):
        return None

    raw = token[1:].lower().strip()

    if raw == "tomorrow":
        return today + timedelta(days=1)

    if raw == "next-week":
        # Monday of the next calendar week
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return today + timedelta(days=days_until_monday)

    _day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if raw in _day_names:
        target_weekday = _day_names.index(raw)
        days_ahead = (target_weekday - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # next occurrence, not today
        return today + timedelta(days=days_ahead)

    # ISO date: @YYYY-MM-DD
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


async def _api_post(
    http: httpx.AsyncClient,
    path: str,
    body: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    """POST to the Open Brain API and return the response JSON."""
    resp = await http.post(
        f"{settings.open_brain_api_url}{path}",
        json=body,
        headers={"X-API-Key": settings.api_key},
    )
    resp.raise_for_status()
    return dict(resp.json())


async def _api_patch(
    http: httpx.AsyncClient,
    path: str,
    body: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    """PATCH to the Open Brain API and return the response JSON."""
    resp = await http.patch(
        f"{settings.open_brain_api_url}{path}",
        json=body,
        headers={"X-API-Key": settings.api_key},
    )
    resp.raise_for_status()
    return dict(resp.json())


async def _api_get(
    http: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    settings: Any,
) -> Any:
    """GET from the Open Brain API and return the response JSON."""
    resp = await http.get(
        f"{settings.open_brain_api_url}{path}",
        params=params,
        headers={"X-API-Key": settings.api_key},
    )
    resp.raise_for_status()
    return resp.json()


def _build_todo_embed(todos: list[dict[str, Any]], title: str = "Open Todos") -> discord.Embed:
    """Build a Discord embed listing open todos."""
    embed = discord.Embed(title=title, color=discord.Color.blue())
    if not todos:
        embed.description = "No open todos. 🎉"
        return embed
    for t in todos[:10]:  # Discord embed limit
        priority_icon = {"high": "🔴", "normal": "🟡", "low": "🟢"}.get(t.get("priority", "normal"), "🟡")
        due = t.get("due_date")
        due_str = f" · due {due[:10]}" if due else ""
        short_id = str(t["id"])[:8]
        embed.add_field(
            name=f"{priority_icon} [{short_id}] {t['description'][:80]}",
            value=f"status: {t['status']}{due_str}",
            inline=False,
        )
    return embed


# ── Interactive UI ─────────────────────────────────────────────────────────────


class DoneButton(discord.ui.Button):
    """Mark a todo as done and update the embed in-place."""

    def __init__(self, todo_id: str, http: httpx.AsyncClient) -> None:
        super().__init__(label="✅ Done", style=discord.ButtonStyle.success, custom_id=f"todo_done_{todo_id}")
        self._todo_id = todo_id
        self._http = http

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        try:
            await _api_patch(self._http, f"/v1/todos/{self._todo_id}", {"status": "done"}, settings)
            await interaction.response.edit_message(
                content=f"✅ Todo `{self._todo_id[:8]}` marked done.",
                embed=None,
                view=None,
            )
        except httpx.HTTPStatusError as exc:
            logger.error("done_button_error", status=exc.response.status_code)
            await interaction.response.send_message("Failed to mark todo as done.", ephemeral=True)


class DeferModal(discord.ui.Modal, title="Defer Todo"):
    """Modal for collecting a new due date (and optional reason)."""

    new_date = discord.ui.TextInput(
        label="New due date (@tomorrow, @monday, @YYYY-MM-DD)",
        placeholder="@tomorrow",
        required=True,
        max_length=20,
    )
    reason = discord.ui.TextInput(
        label="Reason (optional)",
        required=False,
        max_length=200,
    )

    def __init__(self, todo_id: str, http: httpx.AsyncClient) -> None:
        super().__init__()
        self._todo_id = todo_id
        self._http = http

    async def on_submit(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        parsed = parse_natural_date(str(self.new_date.value), date.today())
        if parsed is None:
            await interaction.response.send_message(
                f"Could not parse date `{self.new_date.value}`. "
                "Use @tomorrow, @monday–@sunday, @next-week, or @YYYY-MM-DD.",
                ephemeral=True,
            )
            return

        body: dict[str, Any] = {"due_date": parsed.isoformat() + "T00:00:00Z"}
        if self.reason.value:
            body["reason"] = str(self.reason.value)

        try:
            await _api_patch(self._http, f"/v1/todos/{self._todo_id}", body, settings)
            await interaction.response.edit_message(
                content=f"📅 Todo `{self._todo_id[:8]}` deferred to {parsed.isoformat()}.",
                embed=None,
                view=None,
            )
        except httpx.HTTPStatusError as exc:
            logger.error("defer_modal_error", status=exc.response.status_code)
            await interaction.response.send_message("Failed to defer todo.", ephemeral=True)


class DeferButton(discord.ui.Button):
    """Open the DeferModal for this todo."""

    def __init__(self, todo_id: str, http: httpx.AsyncClient) -> None:
        super().__init__(label="📅 Defer", style=discord.ButtonStyle.secondary, custom_id=f"todo_defer_{todo_id}")
        self._todo_id = todo_id
        self._http = http

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        await interaction.response.send_modal(DeferModal(self._todo_id, self._http))


class TodoView(discord.ui.View):
    """View with Done + Defer buttons for a single todo."""

    def __init__(self, todo_id: str, http: httpx.AsyncClient) -> None:
        super().__init__(timeout=None)  # persistent — survives bot restarts
        self.add_item(DoneButton(todo_id, http))
        self.add_item(DeferButton(todo_id, http))


# ── Slash command group ────────────────────────────────────────────────────────


class TodoGroup(app_commands.Group):
    """Slash command group: /todo <subcommand>."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        super().__init__(name="todo", description="Manage your todos")
        self._http = http

    @app_commands.command(name="list", description="Show open todos")
    async def list_todos(self, interaction: discord.Interaction) -> None:
        """List all open todos as an embed.

        Raises:
            Ephemeral error if API is unreachable.
        """
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            data = await _api_get(self._http, "/v1/todos", {"status": "open", "limit": 10}, settings)
            todos = data.get("todos", [])
        except httpx.HTTPStatusError as exc:
            logger.error("todo_list_error", status=exc.response.status_code)
            await interaction.followup.send("Failed to fetch todos.", ephemeral=True)
            return

        embed = _build_todo_embed(todos)
        if todos:
            # Show buttons for the first todo only (most common action target)
            first_id = todos[0]["id"]
            view = TodoView(first_id, self._http)
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="add", description="Add a new todo")
    @app_commands.describe(
        text="Todo description",
        due="Due date (@tomorrow, @monday–@sunday, @next-week, @YYYY-MM-DD)",
        priority="Priority: high, normal (default), low",
    )
    async def add_todo(
        self,
        interaction: discord.Interaction,
        text: str,
        due: str | None = None,
        priority: str = "normal",
    ) -> None:
        """Create a new todo, optionally with a due date and priority.

        Raises:
            Ephemeral error on invalid date token or API failure.
        """
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return

        due_date: str | None = None
        if due is not None:
            parsed = parse_natural_date(due, date.today())
            if parsed is None:
                await interaction.response.send_message(
                    f"Could not parse due date `{due}`. "
                    "Use @tomorrow, @monday–@sunday, @next-week, or @YYYY-MM-DD.",
                    ephemeral=True,
                )
                return
            due_date = parsed.isoformat() + "T00:00:00Z"

        await interaction.response.defer()
        body: dict[str, Any] = {"description": text, "priority": priority}
        if due_date:
            body["due_date"] = due_date

        try:
            todo = await _api_post(self._http, "/v1/todos", body, settings)
        except httpx.HTTPStatusError as exc:
            logger.error("todo_add_error", status=exc.response.status_code)
            await interaction.followup.send("Failed to create todo.", ephemeral=True)
            return

        short_id = str(todo["id"])[:8]
        priority_icon = {"high": "🔴", "normal": "🟡", "low": "🟢"}.get(priority, "🟡")
        due_str = f" · due {todo['due_date'][:10]}" if todo.get("due_date") else ""
        view = TodoView(todo["id"], self._http)
        await interaction.followup.send(
            f"{priority_icon} Created `{short_id}`: **{text}**{due_str}",
            view=view,
        )

    @app_commands.command(name="done", description="Mark a todo as done")
    @app_commands.describe(todo_id="Todo ID (first 8 characters or full UUID)")
    async def done_todo(self, interaction: discord.Interaction, todo_id: str) -> None:
        """Mark a todo as done by ID.

        Raises:
            Ephemeral error if todo not found or API failure.
        """
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await _api_patch(self._http, f"/v1/todos/{todo_id}", {"status": "done"}, settings)
            await interaction.followup.send(f"✅ Todo `{todo_id[:8]}` marked done.", ephemeral=True)
        except httpx.HTTPStatusError as exc:
            logger.error("todo_done_error", status=exc.response.status_code)
            await interaction.followup.send(
                f"Failed to mark todo done (HTTP {exc.response.status_code}).", ephemeral=True
            )

    @app_commands.command(name="defer", description="Defer a todo to a new date")
    @app_commands.describe(
        todo_id="Todo ID (first 8 characters or full UUID)",
        due="New due date (@tomorrow, @monday–@sunday, @next-week, @YYYY-MM-DD)",
        reason="Optional reason for deferring",
    )
    async def defer_todo(
        self,
        interaction: discord.Interaction,
        todo_id: str,
        due: str,
        reason: str | None = None,
    ) -> None:
        """Defer a todo to a new date.

        Raises:
            Ephemeral error if date cannot be parsed or API fails.
        """
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return

        parsed = parse_natural_date(due, date.today())
        if parsed is None:
            await interaction.response.send_message(
                f"Could not parse date `{due}`. "
                "Use @tomorrow, @monday–@sunday, @next-week, or @YYYY-MM-DD.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        body: dict[str, Any] = {"due_date": parsed.isoformat() + "T00:00:00Z"}
        if reason:
            body["reason"] = reason

        try:
            await _api_patch(self._http, f"/v1/todos/{todo_id}", body, settings)
            await interaction.followup.send(
                f"📅 Todo `{todo_id[:8]}` deferred to {parsed.isoformat()}.", ephemeral=True
            )
        except httpx.HTTPStatusError as exc:
            logger.error("todo_defer_error", status=exc.response.status_code)
            await interaction.followup.send(
                f"Failed to defer todo (HTTP {exc.response.status_code}).", ephemeral=True
            )
