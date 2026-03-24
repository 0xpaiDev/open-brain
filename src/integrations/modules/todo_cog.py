"""Discord slash commands and channel listener for the Todo module.

Provides:
  - /todo list   — tabbed embed (Today / This Week / All) with per-todo buttons
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

_TODOS_PER_PAGE = 5
_VIEW_TIMEOUT = 900  # 15 minutes


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
    days_to_sunday = 6 - today.weekday()  # weekday: Mon=0, Sun=6
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


def _build_tabbed_embed(
    todos: list[dict[str, Any]],
    tab: str,
    page: int,
    total_in_tab: int,
    today: date,
) -> discord.Embed:
    """Build a rich embed for a tab view with pagination.

    Each todo is a separate embed field:
      ☐ [N] 🟡 Description
          Created 2d ago · due Fri Mar 28 ⚠️ (if overdue)

    Footer includes page indicator and button expiry note.
    """
    tab_titles = {"today": "Today", "week": "This Week", "all": "All Todos"}
    tab_empty = {
        "today": "Nothing due today. Add one with `+ task text` or the Add button.",
        "week": "Clear week ahead.",
        "all": "No active todos.",
    }

    title = tab_titles.get(tab, "Todos")
    embed = discord.Embed(title=title, color=discord.Color.blue())

    if not todos:
        embed.description = tab_empty.get(tab, "No todos.")
        return embed

    start = page * _TODOS_PER_PAGE
    page_todos = todos[start : start + _TODOS_PER_PAGE]
    total_pages = max(1, (total_in_tab + _TODOS_PER_PAGE - 1) // _TODOS_PER_PAGE)

    for i, t in enumerate(page_todos, start=start + 1):
        priority_icon = {"high": "🔴", "normal": "🟡", "low": "🟢"}.get(
            t.get("priority", "normal"), "🟡"
        )

        due = t.get("due_date")
        is_overdue = False
        due_str = ""
        if due:
            due_date = datetime.fromisoformat(due.replace("Z", "+00:00")).date()
            due_str = f" · due {due_date.strftime('%a %b %d')}"
            is_overdue = due_date < today

        warning = " ⚠️" if is_overdue else ""

        created_str = ""
        created = t.get("created_at")
        if created:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_days = (datetime.now(tz=created_dt.tzinfo) - created_dt).days
            if age_days == 0:
                created_str = " · today"
            elif age_days == 1:
                created_str = " · 1d ago"
            else:
                created_str = f" · {age_days}d ago"

        embed.add_field(
            name=f"☐ [{i}] {priority_icon} {t['description'][:80]}",
            value=f"Created{created_str}{due_str}{warning}",
            inline=False,
        )

    if total_pages > 1:
        embed.set_footer(
            text=(
                f"Page {page + 1}/{total_pages} · "
                "Buttons expire after 15 min. Use /todo list to refresh."
            )
        )
    else:
        embed.set_footer(text="Buttons expire after 15 min. Use /todo list to refresh.")

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


# ── UI helpers ─────────────────────────────────────────────────────────────────


def _build_tab_view(
    http: httpx.AsyncClient,
    all_todos: list[dict[str, Any]],
    tab: str,
    page: int,
    today: date,
) -> tuple[discord.Embed, "TabView"]:
    """Build (embed, view) for the given tab and page."""
    if tab == "today":
        filtered = _filter_today(all_todos, today)
    elif tab == "week":
        filtered = _filter_week(all_todos, today)
    else:
        filtered = list(all_todos)

    total = len(filtered)
    embed = _build_tabbed_embed(filtered, tab, page, total, today)
    view = TabView(http, all_todos, tab, page, today, filtered)
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

    def __init__(self, http: httpx.AsyncClient, current_tab: str, today: date) -> None:
        super().__init__()
        self._http = http
        self._current_tab = current_tab
        self._today = today

    async def on_submit(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        text = str(self.task.value)

        # Extract @date token if present
        due_date: str | None = None
        match = re.search(r"@(\S+)", text)
        if match:
            token = f"@{match.group(1)}"
            parsed = parse_natural_date(token, self._today)
            if parsed:
                due_date = parsed.isoformat() + "T00:00:00Z"
                text = text[: match.start()].strip()

        body: dict[str, Any] = {"description": text, "priority": "normal"}
        if due_date:
            body["due_date"] = due_date

        try:
            await _api_post(self._http, "/v1/todos", body, settings)
            all_todos = await _fetch_all_open_todos(self._http, settings)
            embed, view = _build_tab_view(self._http, all_todos, self._current_tab, 0, self._today)
            await interaction.response.edit_message(embed=embed, view=view)
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

    def __init__(
        self, todo_id: str, http: httpx.AsyncClient, current_tab: str, today: date
    ) -> None:
        super().__init__()
        self._todo_id = todo_id
        self._http = http
        self._current_tab = current_tab
        self._today = today

    async def on_submit(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        parsed = parse_natural_date(str(self.new_date.value), self._today)
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
            all_todos = await _fetch_all_open_todos(self._http, settings)
            embed, view = _build_tab_view(
                self._http, all_todos, self._current_tab, 0, self._today
            )
            await interaction.response.edit_message(embed=embed, view=view)
        except httpx.HTTPError as exc:
            logger.error("defer_modal_error", error=str(exc))
            await interaction.response.send_message("Failed to defer todo.", ephemeral=True)


# ── Button classes ─────────────────────────────────────────────────────────────


class _TabButton(discord.ui.Button):
    """Switch to a tab and refresh the embed in-place."""

    def __init__(
        self,
        label: str,
        tab: str,
        active: bool,
        http: httpx.AsyncClient,
        all_todos: list[dict[str, Any]],
        today: date,
        row: int,
    ) -> None:
        style = discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary
        super().__init__(label=label, style=style, row=row)
        self._tab = tab
        self._http = http
        self._all_todos = all_todos
        self._today = today

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        embed, view = _build_tab_view(self._http, self._all_todos, self._tab, 0, self._today)
        await interaction.response.edit_message(embed=embed, view=view)


class _AddButton(discord.ui.Button):
    """Open the AddTodoModal."""

    def __init__(self, http: httpx.AsyncClient, tab: str, today: date, row: int) -> None:
        super().__init__(label="+ Add", style=discord.ButtonStyle.success, row=row)
        self._http = http
        self._tab = tab
        self._today = today

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        await interaction.response.send_modal(AddTodoModal(self._http, self._tab, self._today))


class DoneButton(discord.ui.Button):
    """Mark a todo as done and refresh the embed."""

    def __init__(
        self,
        index: int,
        todo_id: str,
        http: httpx.AsyncClient,
        tab: str,
        today: date,
        row: int,
    ) -> None:
        super().__init__(
            label=f"✅ {index}",
            style=discord.ButtonStyle.success,
            custom_id=f"todo_done_{todo_id}",
            row=row,
        )
        self._todo_id = todo_id
        self._http = http
        self._tab = tab
        self._today = today

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        try:
            await _api_patch(self._http, f"/v1/todos/{self._todo_id}", {"status": "done"}, settings)
            all_todos = await _fetch_all_open_todos(self._http, settings)
            embed, view = _build_tab_view(self._http, all_todos, self._tab, 0, self._today)
            await interaction.response.edit_message(embed=embed, view=view)
        except httpx.HTTPError as exc:
            logger.error("done_button_error", error=str(exc))
            await interaction.response.send_message("Failed to mark todo as done.", ephemeral=True)


class DeferButton(discord.ui.Button):
    """Open the DeferModal for this todo."""

    def __init__(
        self,
        index: int,
        todo_id: str,
        http: httpx.AsyncClient,
        tab: str,
        today: date,
        row: int,
    ) -> None:
        super().__init__(
            label=f"📅 {index}",
            style=discord.ButtonStyle.secondary,
            custom_id=f"todo_defer_{todo_id}",
            row=row,
        )
        self._todo_id = todo_id
        self._http = http
        self._tab = tab
        self._today = today

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        await interaction.response.send_modal(
            DeferModal(self._todo_id, self._http, self._tab, self._today)
        )


class _ShowMoreButton(discord.ui.Button):
    """Advance to the next page of todos."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        all_todos: list[dict[str, Any]],
        tab: str,
        next_page: int,
        today: date,
        row: int,
    ) -> None:
        super().__init__(label="▼ More", style=discord.ButtonStyle.secondary, row=row)
        self._http = http
        self._all_todos = all_todos
        self._tab = tab
        self._next_page = next_page
        self._today = today

    async def callback(self, interaction: discord.Interaction) -> None:
        settings = _get_settings()
        if not require_allowed_user(interaction, settings):
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        embed, view = _build_tab_view(
            self._http, self._all_todos, self._tab, self._next_page, self._today
        )
        await interaction.response.edit_message(embed=embed, view=view)


# ── Main view ──────────────────────────────────────────────────────────────────


class TabView(discord.ui.View):
    """Rich embed view with tab switchers and per-todo Done/Defer buttons.

    Button layout (max 5 ActionRows × 5 buttons):
      Row 0: [Today] [This Week] [All] [+ Add]         — tab controls
      Row 1: [✅ 1] [✅ 2] [✅ 3] [✅ 4] [✅ 5]          — done buttons
      Row 2: [📅 1] [📅 2] [📅 3] [📅 4] [📅 5]          — defer buttons
      Row 3: [▼ More]                                   — pagination (if needed)
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        all_todos: list[dict[str, Any]],
        tab: str,
        page: int,
        today: date,
        filtered_todos: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(timeout=_VIEW_TIMEOUT)
        self._http = http
        self._all_todos = all_todos
        self._tab = tab
        self._page = page
        self._today = today

        if filtered_todos is None:
            if tab == "today":
                filtered_todos = _filter_today(all_todos, today)
            elif tab == "week":
                filtered_todos = _filter_week(all_todos, today)
            else:
                filtered_todos = list(all_todos)

        self._filtered = filtered_todos
        self._page_todos = filtered_todos[page * _TODOS_PER_PAGE : (page + 1) * _TODOS_PER_PAGE]

        self._build_buttons()

    def _build_buttons(self) -> None:
        # Row 0: tab switchers + add
        self.add_item(
            _TabButton("Today", "today", self._tab == "today", self._http, self._all_todos, self._today, row=0)
        )
        self.add_item(
            _TabButton("This Week", "week", self._tab == "week", self._http, self._all_todos, self._today, row=0)
        )
        self.add_item(
            _TabButton("All", "all", self._tab == "all", self._http, self._all_todos, self._today, row=0)
        )
        self.add_item(_AddButton(self._http, self._tab, self._today, row=0))

        if not self._page_todos:
            return

        # Row 1: Done buttons for each todo on this page
        for i, t in enumerate(self._page_todos, start=self._page * _TODOS_PER_PAGE + 1):
            self.add_item(DoneButton(i, t["id"], self._http, self._tab, self._today, row=1))

        # Row 2: Defer buttons for each todo on this page
        for i, t in enumerate(self._page_todos, start=self._page * _TODOS_PER_PAGE + 1):
            self.add_item(DeferButton(i, t["id"], self._http, self._tab, self._today, row=2))

        # Row 3: Show More (if there are more pages)
        total = len(self._filtered)
        if (self._page + 1) * _TODOS_PER_PAGE < total:
            self.add_item(
                _ShowMoreButton(
                    self._http, self._all_todos, self._tab, self._page + 1, self._today, row=3
                )
            )


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
            due_str = f" · due {todo['due_date'][:10]}" if todo.get("due_date") else ""
            await message.add_reaction("✅")
            await message.reply(f"✓ Added — {text_part}{due_str}")
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
            await message.add_reaction("✅")
            names = ", ".join(t["description"][:40] for t in today_todos)
            await message.reply(f"✓ Done: {names}")
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
                await message.add_reaction("✅")
                await message.reply(f"✓ Done: {', '.join(completed)}")
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
            await message.add_reaction("✅")
            await message.reply(
                f"✓ Deferred '{t['description'][:40]}' to {parsed_defer.isoformat()}{reason_str}"
            )
        except httpx.HTTPError as exc:
            logger.error("prefix_defer_error", error=str(exc))
            await message.reply("Failed to defer todo.")
        return

    # ── No pattern matched — send hint ────────────────────────────────────────
    await message.reply(
        "Didn't catch that. Try:\n"
        "`+ task text @friday` — add todo\n"
        "`done 1,3` — mark done by index\n"
        "`done all` — mark all today's todos done\n"
        "`defer 2 tomorrow reason` — defer todo"
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
        """Show a rich tabbed embed of open todos.

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
        embed, view = _build_tab_view(self._http, all_todos, "today", 0, today)
        await interaction.followup.send(embed=embed, view=view)

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
        except httpx.HTTPError as exc:
            logger.error("todo_add_error", error=str(exc))
            await interaction.followup.send("Failed to create todo.", ephemeral=True)
            return

        short_id = str(todo["id"])[:8]
        priority_icon = {"high": "🔴", "normal": "🟡", "low": "🟢"}.get(priority, "🟡")
        due_str = f" · due {todo['due_date'][:10]}" if todo.get("due_date") else ""
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
            await interaction.followup.send(f"✅ Todo `{todo_id[:8]}` marked done.", ephemeral=True)
        except httpx.HTTPError as exc:
            logger.error("todo_done_error", error=str(exc))
            await interaction.followup.send("Failed to mark todo done.", ephemeral=True)

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
        except httpx.HTTPError as exc:
            logger.error("todo_defer_error", error=str(exc))
            await interaction.followup.send("Failed to defer todo.", ephemeral=True)
