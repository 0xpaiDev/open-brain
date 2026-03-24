"""Tests for module-conditional command registration in OpenBrainBot.

Verifies that:
- Core commands (/search, /digest, /status) are always registered.
- Module cog commands (e.g. /todo) are only registered when their feature flag is enabled.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrations.discord_bot import OpenBrainBot


def _make_settings(
    *,
    module_todo_enabled: bool = False,
    module_pulse_enabled: bool = False,
    module_rag_chat_enabled: bool = False,
) -> MagicMock:
    """Minimal settings mock with controllable module flags."""
    return MagicMock(
        discord_allowed_user_ids=[42],
        api_key="test-key",
        open_brain_api_url="http://localhost:8000",
        module_todo_enabled=module_todo_enabled,
        module_pulse_enabled=module_pulse_enabled,
        module_rag_chat_enabled=module_rag_chat_enabled,
    )


def _command_names(bot: OpenBrainBot) -> set[str]:
    """Return the set of top-level command/group names registered on the tree."""
    return {cmd.name for cmd in bot.tree.get_commands()}


@pytest.mark.asyncio
async def test_core_commands_always_registered_when_modules_disabled() -> None:
    """Core commands are present even when all module flags are off."""
    http = AsyncMock()
    bot = OpenBrainBot(http)
    mock_settings = _make_settings(
        module_todo_enabled=False,
        module_pulse_enabled=False,
        module_rag_chat_enabled=False,
    )

    with patch("src.integrations.discord_bot._get_settings", return_value=mock_settings):
        with patch.object(bot.tree, "sync", new_callable=AsyncMock, return_value=[]):
            await bot.setup_hook()

    names = _command_names(bot)
    assert "search" in names
    assert "digest" in names
    assert "status" in names


@pytest.mark.asyncio
async def test_todo_command_absent_when_flag_disabled() -> None:
    """/todo group is NOT registered when module_todo_enabled=False."""
    http = AsyncMock()
    bot = OpenBrainBot(http)
    mock_settings = _make_settings(module_todo_enabled=False)

    with patch("src.integrations.discord_bot._get_settings", return_value=mock_settings):
        with patch.object(bot.tree, "sync", new_callable=AsyncMock, return_value=[]):
            await bot.setup_hook()

    assert "todo" not in _command_names(bot)


@pytest.mark.asyncio
async def test_todo_command_present_when_flag_enabled() -> None:
    """/todo group IS registered when module_todo_enabled=True."""
    http = AsyncMock()
    bot = OpenBrainBot(http)
    mock_settings = _make_settings(module_todo_enabled=True)

    # Stub out TodoGroup so the import doesn't fail before todo_cog.py is written.
    # In production the real TodoGroup is a discord.app_commands.Group.
    from discord import app_commands

    class _FakeTodoGroup(app_commands.Group):
        def __init__(self, http_client):  # type: ignore[override]
            super().__init__(name="todo", description="Manage todos")

    fake_cog_module = MagicMock()
    fake_cog_module.TodoGroup = _FakeTodoGroup

    with patch.dict(sys.modules, {"src.integrations.modules.todo_cog": fake_cog_module}):
        with patch("src.integrations.discord_bot._get_settings", return_value=mock_settings):
            with patch.object(bot.tree, "sync", new_callable=AsyncMock, return_value=[]):
                await bot.setup_hook()

    assert "todo" in _command_names(bot)
    # Core commands still present
    assert "search" in _command_names(bot)
    assert "digest" in _command_names(bot)
    assert "status" in _command_names(bot)


@pytest.mark.asyncio
async def test_core_commands_present_alongside_todo() -> None:
    """When todo is enabled, core commands coexist with /todo."""
    http = AsyncMock()
    bot = OpenBrainBot(http)
    mock_settings = _make_settings(module_todo_enabled=True)

    from discord import app_commands

    class _FakeTodoGroup(app_commands.Group):
        def __init__(self, http_client):  # type: ignore[override]
            super().__init__(name="todo", description="Manage todos")

    fake_cog_module = MagicMock()
    fake_cog_module.TodoGroup = _FakeTodoGroup

    with patch.dict(sys.modules, {"src.integrations.modules.todo_cog": fake_cog_module}):
        with patch("src.integrations.discord_bot._get_settings", return_value=mock_settings):
            with patch.object(bot.tree, "sync", new_callable=AsyncMock, return_value=[]):
                await bot.setup_hook()

    names = _command_names(bot)
    assert {"search", "digest", "status", "todo"}.issubset(names)
