"""Discord slash commands and channel listener for the Todo module.

Provides:
  - /todo list   — select-menu embed (Today / This Week / All) with dropdown + action buttons
  - /todo add    — create a todo via slash command
  - /todo done   — mark done via slash command
  - /todo defer  — defer via slash command
  - on_message   — channel prefix listener (+ text, done N, defer N date reason)
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

import discord
import httpx
import structlog
from discord import app_commands

from src.integrations.kernel import _get_settings, require_allowed_user

logger = structlog.get_logger(__name__)

_VIEW_TIMEOUT = 840   # 14 minutes (under Discord's 15-min limit)
_MAX_SELECT = 25      # Discord select menu hard limit

_COLOR_OK = 0x5865F2       # blurple — all clear
_COLOR_OVERDUE = 0xFAA61A  # amber — has overdue items


# ── Pure helpers ───────────────────────────────────────────────────────────────


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
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return today + timedelta(days=days_until_monday)

    _day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if raw in _day_names:
        target_weekday = _day_names.index(raw)
        days_ahead = (target_weekday - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return today + timedelta(days=days_ahead)

    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_date_bare(token: str, today: date) -> date | None:
    """Parse a bare date token (without @ prefix). Wraps parse_natural_date."""
    return parse_natural_date(f"@{token.lower().strip()}", today)


def _filter_today(todos: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Return todos due today or earlier, or with no due date."""
    result = []
    for t in todos:
        due = t.get("due_date")
        if due is None:
            result.append(t)
        else:
            due_date = datetime.fromisoformat(due.replace("Z", "+00:00")).date()
            if due_date <= today:
                result.append(t)
    return result


def _filter_week(todos: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Return todos due this week (through Sunday) or earlier, or with no due date."""
    days_to_sunday = 6 - today.weekday()
    end_of_week = today + timedelta(days=days_to_sunday)
    result = []
    for t in todos:
        due = t.get("due_date")
        if due is None:
            result.append(t)
        else:
            due_date = datetime.fromisoformat(due.replace("Z", "+00:00")).date()
            if due_date <= end_of_week:
                result.append(t)
    return result


# ── Display helpers ────────────────────────────────────────────────────────────


def _parse_iso_date(iso_str: str | None) -> date | None:
    """Parse an ISO 8601 datetime string to a date, or None on failure."""
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _humanize_age(created_at: str | None) -> str:
    """Return a human-readable age string for a created_at ISO timestamp."""
    if not created_at:
        return "unknown"
    try:
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age_days = (datetime.now(tz=created_dt.tzinfo) - created_dt).days
        if age_days == 0:
            return "created today"
        elif age_days == 1:
            return "created 1d ago"
        else:
            return f"created {age_days}d ago"
    except ValueError:
        return "unknown"


def format_todo_line(index: int, todo: dict[str, Any], today: date) -> str:
    """Format a single todo as two monospace lines for the code-block embed.

    Line 1: │ N. Description  [⚠ marker] [priority]
    Line 2: │    created Xd ago
    """
    description = str(todo.get("description", ""))[:78]
    line1 = f"\u2502 {index}. {description}"

    markers: list[str] = []
    due = _parse_iso_date(todo.get("due_date"))
    if due is not None:
        if due == today:
            markers.append("\u26a0 due today")
        elif due < today:
            markers.append("\u26a0 overdue")

    priority = todo.get("priority", "normal")
    if priority not in (None, "normal"):
        markers.append(str(priority))

    if markers:
        line1 += "  " + " \u00b7 ".join(markers)

    line2 = f"\u2502    {_humanize_age(todo.get('created_at'))}"
    return f"{line1}\n{line2}"


def build_embed(todos: list[dict[str, Any]], tab: str, today: date) -> discord.Embed:
    """Build a Discord embed with a monospace code-block todo list.

    Uses a triple-backtick code block for visual containment and monospace alignment.
    Embed color reflects overall status: blurple (ok) or amber (has overdue items).
    """
    _TAB_TITLES = {"today": "Today", "week": "This Week", "all": "All Todos"}
    _TAB_EMPTY = {
        "today": "No tasks for today. Use + Add or type: `+ fix the bug @friday`",
        "week": "Clear week ahead.",
        "all": "No active todos.",
    }

    n = len(todos)
    task_word = "task" if n == 1 else "tasks"
    title = f"\U0001f4cb {_TAB_TITLES.get(tab, 'Todos')} \u00b7 {n} {task_word}"

    has_overdue = any(
        (d := _parse_iso_date(t.get("due_date"))) is not None and d < today
        for t in todos
    )
    color = _COLOR_OVERDUE if has_overdue else _COLOR_OK

    embed = discord.Embed(title=title, color=color)

    if not todos:
        embed.description = _TAB_EMPTY.get(tab, "No todos.")
    else:
        lines = ["\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                 "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                 "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"]
        for i, t in enumerate(todos, 1):
            lines.append(format_todo_line(i, t, today))
            if i < len(todos):
                lines.append("\u2502")
        lines.append("\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                     "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
                     "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        embed.description = "```\n" + "\n".join(lines) + "\n```"

    hint = "\u2705 done 1,3  \u00b7  \u23ed\ufe0f defer 2 tomorrow reason  \u00b7  + task @fri"
    embed.set_footer(text=f"{hint}\nButtons expire after 15 min. Use /todo list to refresh.")

    return embed


# ── API helpers ────────────────────────────────────────────────────────────────


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
        headers={"X-API-Key": settings.api_key.get_secret_value()},
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
        headers={"X-API-Key": settings.api_key.get_secret_value()},
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
        headers={"X-API-Key": settings.api_key.get_secret_value()},
    )
    resp.raise_for_status()
    return resp.json()


async def _fetch_all_open_todos(http: httpx.AsyncClient, settings: Any) -> list[dict[str, Any]]:
    """Fetch all open todos (up to 200). Returns raw list."""
    data = await _api_get(http, "/v1/todos", {"status": "open", "limit": 200}, settings)
    return data.get("todos", [])


# ── UI helper ──────────────────────────────────────────────────────────────────


def _build_todo_view(
    http: httpx.AsyncClient,
    all_todos: list[dict[str, Any]],
    tab: str,
    today: date,
) -> tuple[discord.Embed, "TodoView"]:
    """Build (embed, view) for the given tab. Single source of truth for rendering.

    Every code path — /todo list, tab switch, done, defer, add — calls this.
    """
    if tab == "today":
        filtered = _filter_today(all_todos, today)
    elif tab == "week":
        filtered = _filter_week(all_todos, today)
    else:
        filtered = list(all_todos)

    embed = build_embed(filtered, tab, today)
    view = TodoView(http, all_todos, tab, filtered)
    return embed, view


# ── Modal classes ──────────────────────────────────────────────────────────────


class AddTodoModal(discord.ui.Modal, title="Add Todo"):
    """Modal for quickly adding a todo with optional @date syntax."""

    task = discord.ui.TextInput(
        label="Task (use @friday for due date)",
        placeholder="Fix DNS @friday",
        required=True,
        max_length=200,
    )

    def __init__(self, http: httpx.AsyncClient, current_tab: str) -> None:
        super().__init__()
        self._http = http
        self._current_tab = current_tab

    async def on_submit(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        today = date.today()
        text = str(self.task.value)

        due_date: str | None = None
        match = re.search(r"@(\S+)", text)
        if match:
            token = f"@{match.group(1)}"
            parsed = parse_natural_date(token, today)
            if parsed:
                due_date = parsed.isoformat() + "T00:00:00Z"
                text = text[: match.start()].strip()

        body: dict[str, Any] = {"description": text, "priority": "normal"}
        if due_date:
            body["due_date"] = due_date

        try:
            await _api_post(self._http, "/v1/todos", body, settings)
            all_todos = await _fetch_all_open_todos(self._http, settings)
            embed, view = _build_todo_view(self._http, all_todos, self._current_tab, today)
            await interaction.response.edit_message(embed=embed, view=view)
            due_str = f" \u00b7 due {due_date[:10]}" if due_date else ""
            await interaction.followup.send(f"\u2713 Added \u2014 {text}{due_str}", ephemeral=True)
        except httpx.HTTPError as exc:
            logger.error("add_todo_modal_error", error=str(exc))
            await interaction.response.send_message("Failed to create todo.", ephemeral=True)


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

    def __init__(self, todo_id: str, http: httpx.AsyncClient, current_tab: str) -> None:
        super().__init__()
        self._todo_id = todo_id
        self._http = http
        self._current_tab = current_tab

    async def on_submit(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        today = date.today()
        parsed = parse_natural_date(str(self.new_date.value), today)
        if parsed is None:
            await interaction.response.send_message(
                f"Could not parse date `{self.new_date.value}`. "
                "Use @tomorrow, @monday\u2013@sunday, @next-week, or @YYYY-MM-DD.",
                ephemeral=True,
            )
            return

        body: dict[str, Any] = {"due_date": parsed.isoformat() + "T00:00:00Z"}
        if self.reason.value:
            body["reason"] = str(self.reason.value)

        try:
            await _api_patch(self._http, f"/v1/todos/{self._todo_id}", body, settings)
            all_todos = await _fetch_all_open_todos(self._http, settings)
            embed, view = _build_todo_view(self._http, all_todos, self._current_tab, today)
            await interaction.response.edit_message(embed=embed, view=view)
            reason_str = f" ({self.reason.value})" if self.reason.value else ""
            await interaction.followup.send(
                f"\u23ed\ufe0f Deferred to {parsed.isoformat()}{reason_str}", ephemeral=True
            )
        except httpx.HTTPError as exc:
            logger.error("defer_modal_error", error=str(exc))
            await interaction.response.send_message("Failed to defer todo.", ephemeral=True)


# ── UI components ──────────────────────────────────────────────────────────────


class TodoSelect(discord.ui.Select):
    """Dropdown for selecting which todo to act on. Value = todo UUID."""

    def __init__(self, todos: list[dict[str, Any]]) -> None:
        options = []
        for i, t in enumerate(todos[:_MAX_SELECT], 1):
            due = _parse_iso_date(t.get("due_date"))
            today = date.today()
            if due and due < today:
                meta = "overdue"
            elif due and due == today:
                meta = "due today"
            else:
                meta = _humanize_age(t.get("created_at"))
            options.append(
                discord.SelectOption(
                    label=f"{i}. {str(t.get('description', ''))[:95]}",
                    value=str(t["id"]),
                    description=meta[:100],
                )
            )
        super().__init__(
            placeholder="Select a task...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Acknowledge selection silently — action happens via Done/Defer buttons
        await interaction.response.defer()


class DoneButton(discord.ui.Button):
    """Mark the selected todo as done and refresh the embed."""

    def __init__(self, select: TodoSelect, http: httpx.AsyncClient, tab: str) -> None:
        super().__init__(
            label="\u2705 Done",
            style=discord.ButtonStyle.success,
            row=1,
        )
        self._select = select
        self._http = http
        self._tab = tab

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        if not self._select.values:
            await interaction.response.send_message("Pick a task first.", ephemeral=True)
            return

        todo_id = self._select.values[0]
        desc = next(
            (opt.label.split(". ", 1)[-1] for opt in self._select.options if opt.value == todo_id),
            todo_id[:8],
        )
        today = date.today()
        try:
            await _api_patch(self._http, f"/v1/todos/{todo_id}", {"status": "done"}, settings)
            all_todos = await _fetch_all_open_todos(self._http, settings)
            embed, view = _build_todo_view(self._http, all_todos, self._tab, today)
            await interaction.response.edit_message(embed=embed, view=view)
            await interaction.followup.send(f"\u2705 Done: {desc}", ephemeral=True)
        except httpx.HTTPError as exc:
            logger.error("done_button_error", error=str(exc))
            await interaction.response.send_message("Failed to mark todo as done.", ephemeral=True)


class DeferButton(discord.ui.Button):
    """Open the DeferModal for the selected todo."""

    def __init__(self, select: TodoSelect, http: httpx.AsyncClient, tab: str) -> None:
        super().__init__(
            label="\u23ed\ufe0f Defer",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self._select = select
        self._http = http
        self._tab = tab

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        if not self._select.values:
            await interaction.response.send_message("Pick a task first.", ephemeral=True)
            return

        todo_id = self._select.values[0]
        await interaction.response.send_modal(
            DeferModal(todo_id, self._http, self._tab)
        )


class TabButton(discord.ui.Button):
    """Switch to a different tab and refresh the embed in-place."""

    def __init__(
        self,
        label: str,
        tab: str,
        active: bool,
        http: httpx.AsyncClient,
        *,
        row: int,
    ) -> None:
        style = discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary
        super().__init__(label=label, style=style, row=row)
        self._tab = tab
        self._http = http

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        today = date.today()
        try:
            all_todos = await _fetch_all_open_todos(self._http, settings)
            embed, view = _build_todo_view(self._http, all_todos, self._tab, today)
            await interaction.response.edit_message(embed=embed, view=view)
        except httpx.HTTPError as exc:
            logger.error("tab_button_error", error=str(exc))
            await interaction.response.send_message("Failed to fetch todos.", ephemeral=True)


class AddButton(discord.ui.Button):
    """Open the AddTodoModal."""

    def __init__(self, http: httpx.AsyncClient, tab: str, *, row: int) -> None:
        super().__init__(label="+ Add", style=discord.ButtonStyle.success, row=row)
        self._http = http
        self._tab = tab

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        await interaction.response.send_modal(AddTodoModal(self._http, self._tab))


# ── Main view ──────────────────────────────────────────────────────────────────


class TodoView(discord.ui.View):
    """Select-menu + action buttons view for the todo embed.

    Button layout (max 5 ActionRows):
      When todos exist:
        Row 0: Select menu (dropdown — takes a full row)
        Row 1: [✅ Done]  [⏭️ Defer]
        Row 2: [Today] [This Week] [All] [+ Add]
      When empty:
        Row 0: [Today] [This Week] [All] [+ Add]
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        all_todos: list[dict[str, Any]],
        tab: str,
        filtered_todos: list[dict[str, Any]],
    ) -> None:
        super().__init__(timeout=_VIEW_TIMEOUT)
        self._http = http
        self._tab = tab

        tab_row = 2 if filtered_todos else 0

        if filtered_todos:
            self.todo_select: TodoSelect | None = TodoSelect(filtered_todos)
            self.add_item(self.todo_select)
            self.add_item(DoneButton(self.todo_select, http, tab))
            self.add_item(DeferButton(self.todo_select, http, tab))
        else:
            self.todo_select = None

        self.add_item(TabButton("Today", "today", tab == "today", http, row=tab_row))
        self.add_item(TabButton("This Week", "week", tab == "week", http, row=tab_row))
        self.add_item(TabButton("All", "all", tab == "all", http, row=tab_row))
        self.add_item(AddButton(http, tab, row=tab_row))


# ── on_message handler ─────────────────────────────────────────────────────────

# Module-level handler set by register_todo() — referenced by discord_bot.py guard
_todo_handler: Any | None = None


async def _handle_todo_message(
    message: discord.Message,
    http: httpx.AsyncClient,
    settings: Any,
) -> None:
    """Handle prefix commands in the designated todo channel.

    Patterns:
      + <text>              → create todo (no due date)
      + <text> @<date>      → create todo with due date
      done <n>[,<n>...]     → mark today's todos done by 1-based index
      done all              → mark all of today's todos done
      defer <n> <date> [r]  → defer today's todo by index with optional reason
      (no match)            → reply with help hint, don't ingest as memory
    """
    content = message.content.strip()
    today = date.today()

    # ── Pattern: + <text> [@date] ──────────────────────────────────────────────
    if content.startswith("+"):
        text_part = content[1:].strip()
        if not text_part:
            await message.reply(
                "Didn't catch that. Try: `+ task text @friday` or `done 1,3`"
            )
            return

        due_date: str | None = None
        match = re.search(r"@(\S+)", text_part)
        if match:
            token = f"@{match.group(1)}"
            parsed = parse_natural_date(token, today)
            if parsed:
                due_date = parsed.isoformat() + "T00:00:00Z"
                text_part = text_part[: match.start()].strip()

        body: dict[str, Any] = {"description": text_part, "priority": "normal"}
        if due_date:
            body["due_date"] = due_date

        try:
            todo = await _api_post(http, "/v1/todos", body, settings)
            due_str = f" \u00b7 due {todo['due_date'][:10]}" if todo.get("due_date") else ""
            await message.add_reaction("\u2705")
            await message.reply(f"\u2713 Added \u2014 {text_part}{due_str}")
        except httpx.HTTPError as exc:
            logger.error("prefix_add_error", error=str(exc))
            await message.reply("Failed to create todo.")
        return

    lower = content.lower()

    # ── Pattern: done all ─────────────────────────────────────────────────────
    if lower == "done all":
        try:
            data = await _api_get(http, "/v1/todos", {"status": "open", "limit": 200}, settings)
            todos = data.get("todos", [])
            today_todos = _filter_today(todos, today)
            if not today_todos:
                await message.reply("No open todos for today.")
                return
            for t in today_todos:
                await _api_patch(http, f"/v1/todos/{t['id']}", {"status": "done"}, settings)
            await message.add_reaction("\u2705")
            names = ", ".join(t["description"][:40] for t in today_todos)
            await message.reply(f"\u2713 Done: {names}")
        except httpx.HTTPError as exc:
            logger.error("prefix_done_all_error", error=str(exc))
            await message.reply("Failed to mark todos done.")
        return

    # ── Pattern: done <numbers> ───────────────────────────────────────────────
    m = re.match(r"done\s+([\d,\s]+)$", content, re.IGNORECASE)
    if m:
        raw_nums = re.findall(r"\d+", m.group(1))
        indices = [int(n) for n in raw_nums]
        try:
            data = await _api_get(http, "/v1/todos", {"status": "open", "limit": 200}, settings)
            todos = data.get("todos", [])
            today_todos = _filter_today(todos, today)
            completed: list[str] = []
            for idx in indices:
                if 1 <= idx <= len(today_todos):
                    t = today_todos[idx - 1]
                    await _api_patch(http, f"/v1/todos/{t['id']}", {"status": "done"}, settings)
                    completed.append(t["description"][:40])
            if completed:
                await message.add_reaction("\u2705")
                await message.reply(f"\u2713 Done: {', '.join(completed)}")
            else:
                await message.reply(
                    "No matching todos. Use `/todo list` to see current indices."
                )
        except httpx.HTTPError as exc:
            logger.error("prefix_done_error", error=str(exc))
            await message.reply("Failed to mark todos done.")
        return

    # ── Pattern: defer <n> <date> [reason] ───────────────────────────────────
    m2 = re.match(r"defer\s+(\d+)\s+(\S+)(.*)", content, re.IGNORECASE)
    if m2:
        idx = int(m2.group(1))
        date_token = m2.group(2).strip()
        reason = m2.group(3).strip() or None

        parsed_defer = _parse_date_bare(date_token, today)
        if parsed_defer is None:
            await message.reply(
                f"Could not parse date `{date_token}`. "
                "Try: `defer 1 tomorrow`, `defer 2 friday`, `defer 3 2026-04-01`"
            )
            return

        try:
            data = await _api_get(http, "/v1/todos", {"status": "open", "limit": 200}, settings)
            todos = data.get("todos", [])
            today_todos = _filter_today(todos, today)
            if not (1 <= idx <= len(today_todos)):
                await message.reply(
                    f"No todo at index {idx}. Use `/todo list` to see current todos."
                )
                return
            t = today_todos[idx - 1]
            defer_body: dict[str, Any] = {"due_date": parsed_defer.isoformat() + "T00:00:00Z"}
            if reason:
                defer_body["reason"] = reason
            await _api_patch(http, f"/v1/todos/{t['id']}", defer_body, settings)
            reason_str = f" ({reason})" if reason else ""
            await message.add_reaction("\u2705")
            await message.reply(
                f"\u2713 Deferred '{t['description'][:40]}' to {parsed_defer.isoformat()}{reason_str}"
            )
        except httpx.HTTPError as exc:
            logger.error("prefix_defer_error", error=str(exc))
            await message.reply("Failed to defer todo.")
        return

    # ── No pattern matched — send hint ────────────────────────────────────────
    await message.reply(
        "Didn't catch that. Try:\n"
        "`+ task text @friday` \u2014 add todo\n"
        "`done 1,3` \u2014 mark done by index\n"
        "`done all` \u2014 mark all today's todos done\n"
        "`defer 2 tomorrow reason` \u2014 defer todo"
    )


def register_todo(
    bot: discord.Client,
    http: httpx.AsyncClient,
    settings: Any,
) -> None:
    """Register the TodoGroup slash commands and set up the on_message handler.

    Call this from discord_bot.py's setup_hook instead of adding TodoGroup directly.
    If discord_todo_channel_id is set, messages in that channel route to _handle_todo_message.
    """
    global _todo_handler
    bot.tree.add_command(TodoGroup(http))
    if settings.discord_todo_channel_id:

        async def handler(message: discord.Message) -> None:
            await _handle_todo_message(message, http, settings)

        _todo_handler = handler


# ── Slash command group ────────────────────────────────────────────────────────


class TodoGroup(app_commands.Group):
    """Slash command group: /todo <subcommand>."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        super().__init__(name="todo", description="Manage your todos")
        self._http = http

    @app_commands.command(name="list", description="Show todos with Today / This Week / All tabs")
    async def list_todos(self, interaction: discord.Interaction) -> None:
        """Show a select-menu embed of open todos with action buttons.

        Raises:
            Ephemeral error if API is unreachable.
        """
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            all_todos = await _fetch_all_open_todos(self._http, settings)
        except httpx.HTTPError as exc:
            logger.error("todo_list_error", error=str(exc))
            await interaction.followup.send("Failed to fetch todos.", ephemeral=True)
            return

        today = date.today()
        embed, view = _build_todo_view(self._http, all_todos, "today", today)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="add", description="Add a new todo")
    @app_commands.describe(
        text="Todo description",
        due="Due date (@tomorrow, @monday\u2013@sunday, @next-week, @YYYY-MM-DD)",
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
                    "Use @tomorrow, @monday\u2013@sunday, @next-week, or @YYYY-MM-DD.",
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
        except httpx.HTTPError as exc:
            logger.error("todo_add_error", error=str(exc))
            await interaction.followup.send("Failed to create todo.", ephemeral=True)
            return

        short_id = str(todo["id"])[:8]
        priority_icon = {"high": "\U0001f534", "normal": "\U0001f7e1", "low": "\U0001f7e2"}.get(
            priority, "\U0001f7e1"
        )
        due_str = f" \u00b7 due {todo['due_date'][:10]}" if todo.get("due_date") else ""
        await interaction.followup.send(
            f"{priority_icon} Created `{short_id}`: **{text}**{due_str}"
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
            await interaction.followup.send(f"\u2705 Todo `{todo_id[:8]}` marked done.", ephemeral=True)
        except httpx.HTTPError as exc:
            logger.error("todo_done_error", error=str(exc))
            await interaction.followup.send("Failed to mark todo done.", ephemeral=True)

    @app_commands.command(name="defer", description="Defer a todo to a new date")
    @app_commands.describe(
        todo_id="Todo ID (first 8 characters or full UUID)",
        due="New due date (@tomorrow, @monday\u2013@sunday, @next-week, @YYYY-MM-DD)",
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
                "Use @tomorrow, @monday\u2013@sunday, @next-week, or @YYYY-MM-DD.",
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
                f"\U0001f4c5 Todo `{todo_id[:8]}` deferred to {parsed.isoformat()}.", ephemeral=True
            )
        except httpx.HTTPError as exc:
            logger.error("todo_defer_error", error=str(exc))
            await interaction.followup.send("Failed to defer todo.", ephemeral=True)
