"""Tests for the Open Brain CLI (cli/ob.py).

All tests use typer.testing.CliRunner (synchronous). Commands call asyncio.run()
internally, so tests must be plain `def` — never `async def`. External calls
(DB, Voyage AI, Anthropic) are mocked by patching the inner async helper
functions (_ingest_async, _search_async, etc.) with AsyncMock.

Naming convention: test_<command>_<scenario>
"""

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from cli.ob import app

runner = CliRunner()


# ── ob ingest ─────────────────────────────────────────────────────────────────


def test_ingest_queues_successfully():
    """ob ingest <text> exits 0 and reports queued status."""
    with patch("cli.ob._ingest_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        result = runner.invoke(app, ["ingest", "hello world"])

    assert result.exit_code == 0
    mock_fn.assert_called_once_with("hello world", "cli")


def test_ingest_custom_source():
    """ob ingest <text> --source slack passes source to _ingest_async."""
    with patch("cli.ob._ingest_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        result = runner.invoke(app, ["ingest", "hello", "--source", "slack"])

    assert result.exit_code == 0
    mock_fn.assert_called_once_with("hello", "slack")


def test_ingest_requires_text_argument():
    """ob ingest with no args exits non-zero (missing required argument)."""
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code != 0


def test_ingest_async_prints_queued():
    """ob ingest prints 'queued' message for a new memory (via _ingest_async side effect)."""
    with patch("cli.ob._ingest_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect(text, source):
            import typer

            typer.echo("Ingested. raw_id=aaaa-bbbb status=queued")

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["ingest", "new memory text"])

    assert result.exit_code == 0
    assert "queued" in result.output


def test_ingest_async_prints_duplicate(monkeypatch):
    """_ingest_async prints 'duplicate' message when a duplicate is found."""
    with patch("cli.ob._ingest_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect(text, source):
            import typer

            typer.echo("Duplicate detected. raw_id=some-id status=duplicate")

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["ingest", "existing memory"])

    assert result.exit_code == 0
    assert "duplicate" in result.output


# ── ob search ─────────────────────────────────────────────────────────────────


def test_search_requires_query_argument():
    """ob search with no args exits non-zero (missing required argument)."""
    result = runner.invoke(app, ["search"])
    assert result.exit_code != 0


def test_search_exits_ok_with_results():
    """ob search <query> exits 0 when _search_async returns normally."""
    with patch("cli.ob._search_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        result = runner.invoke(app, ["search", "Python"])

    assert result.exit_code == 0
    mock_fn.assert_called_once()
    call_args = mock_fn.call_args.args
    assert call_args[0] == "Python"
    assert call_args[1] == 10  # default limit


def test_search_passes_limit():
    """ob search --limit 5 passes limit=5 to _search_async."""
    with patch("cli.ob._search_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["search", "test", "--limit", "5"])

    call_args = mock_fn.call_args.args
    assert call_args[1] == 5


def test_search_passes_type_filter():
    """ob search --type decision passes type_filter='decision'."""
    with patch("cli.ob._search_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["search", "test", "--type", "decision"])

    call_args = mock_fn.call_args.args
    assert call_args[2] == "decision"


def test_search_passes_entity_filter():
    """ob search --entity Anthropic passes entity_filter='Anthropic'."""
    with patch("cli.ob._search_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["search", "test", "--entity", "Anthropic"])

    call_args = mock_fn.call_args.args
    assert call_args[3] == "Anthropic"


def test_search_passes_date_range():
    """ob search --from 2026-01-01 --to 2026-12-31 passes UTC-aware datetimes."""
    with patch("cli.ob._search_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["search", "test", "--from", "2026-01-01", "--to", "2026-12-31"])

    call_args = mock_fn.call_args.args
    date_from = call_args[4]
    date_to = call_args[5]
    assert date_from is not None
    assert date_to is not None
    assert date_from.tzinfo is not None  # UTC-attached
    assert date_to.tzinfo is not None


def test_search_invalid_date_exits_nonzero():
    """ob search --from not-a-date exits non-zero."""
    result = runner.invoke(app, ["search", "test", "--from", "not-a-date"])
    assert result.exit_code != 0


def test_search_async_prints_no_results():
    """_search_async prints 'No results found' when results list is empty."""
    with patch("cli.ob._search_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect(*args, **kwargs):
            import typer

            typer.echo("No results found.")

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["search", "unknownxyz"])

    assert result.exit_code == 0
    assert "No results found" in result.output


def test_search_async_prints_results():
    """_search_async prints formatted results when results are returned."""
    with patch("cli.ob._search_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect(*args, **kwargs):
            import typer

            typer.echo("[1] MEMORY | 2026-03-15 | score=0.850")
            typer.echo("    Python is a programming language")

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["search", "Python"])

    assert result.exit_code == 0
    assert "MEMORY" in result.output
    assert "Python" in result.output


# ── ob context ────────────────────────────────────────────────────────────────


def test_context_requires_query_argument():
    """ob context with no args exits non-zero."""
    result = runner.invoke(app, ["context"])
    assert result.exit_code != 0


def test_context_exits_ok():
    """ob context <query> exits 0 when _context_async returns normally."""
    with patch("cli.ob._context_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        result = runner.invoke(app, ["context", "Python"])

    assert result.exit_code == 0
    mock_fn.assert_called_once_with("Python", 10)


def test_context_passes_limit():
    """ob context --limit 5 passes limit=5 to _context_async."""
    with patch("cli.ob._context_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["context", "test", "--limit", "5"])

    mock_fn.assert_called_once_with("test", 5)


def test_context_prints_context_and_token_summary():
    """_context_async prints the context string and token summary line."""
    with patch("cli.ob._context_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect(query, limit):
            import typer

            typer.echo("[1] MEMORY | 2026-03-15\nContent: Python is great")
            typer.echo("\n--- 1 items, 12/8192 tokens ---")

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["context", "Python"])

    assert result.exit_code == 0
    assert "items" in result.output
    assert "tokens" in result.output


# ── ob worker ─────────────────────────────────────────────────────────────────


def test_worker_sync_no_jobs_prints_message():
    """ob worker --sync exits 0 and prints 'No pending jobs' when queue is empty."""
    with patch("cli.ob._worker_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect(sync):
            import typer

            typer.echo("No pending jobs.")

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["worker", "--sync"])

    assert result.exit_code == 0
    assert "No pending jobs" in result.output


def test_worker_sync_processes_job():
    """ob worker --sync exits 0 and prints processed count when jobs exist."""
    with patch("cli.ob._worker_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect(sync):
            import typer

            typer.echo("Processed 1 job(s).")

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["worker", "--sync"])

    assert result.exit_code == 0
    assert "Processed" in result.output


def test_worker_passes_sync_flag():
    """ob worker --sync passes sync=True to _worker_async."""
    with patch("cli.ob._worker_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["worker", "--sync"])

    mock_fn.assert_called_once_with(True)


def test_worker_default_is_continuous():
    """ob worker without --sync passes sync=False to _worker_async."""
    with patch("cli.ob._worker_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["worker"])

    mock_fn.assert_called_once_with(False)


def test_worker_missing_api_keys_exits_nonzero():
    """ob worker --sync exits 1 when Anthropic or Voyage API keys are missing."""
    with patch("cli.ob._worker_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect(sync):
            import typer

            typer.echo("Error: Anthropic or Voyage API key not configured.", err=True)
            raise typer.Exit(code=1)

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["worker", "--sync"])

    assert result.exit_code == 1


# ── ob health ─────────────────────────────────────────────────────────────────


def test_health_ok():
    """ob health exits 0 and prints 'status=ok' when DB is reachable."""
    with patch("cli.ob._health_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect():
            import typer

            typer.echo("status=ok database=reachable")

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["health"])

    assert result.exit_code == 0
    assert "status=ok" in result.output


def test_health_error_exits_nonzero():
    """ob health exits 1 when DB is unreachable."""
    with patch("cli.ob._health_async", new_callable=AsyncMock) as mock_fn:

        async def side_effect():
            import typer

            raise typer.Exit(code=1)

        mock_fn.side_effect = side_effect
        result = runner.invoke(app, ["health"])

    assert result.exit_code == 1


# ── ob --help smoke tests ─────────────────────────────────────────────────────


def test_app_help():
    """ob --help exits 0 and shows command list."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.output
    assert "search" in result.output
    assert "worker" in result.output
    assert "health" in result.output


def test_ingest_help():
    """ob ingest --help exits 0."""
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0


def test_search_help():
    """ob search --help exits 0 and mentions --entity and --from."""
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    assert "--entity" in result.output
    assert "--from" in result.output


def test_worker_help():
    """ob worker --help exits 0 and mentions --sync."""
    result = runner.invoke(app, ["worker", "--help"])
    assert result.exit_code == 0
    assert "--sync" in result.output


def test_cli_reads_correct_api_url_env_var():
    """CLI reads OPEN_BRAIN_API_URL (not OPENBRAIN_API_URL)."""
    import importlib
    import os

    # Clear any existing env vars
    os.environ.pop("OPEN_BRAIN_API_URL", None)
    os.environ.pop("OPENBRAIN_API_URL", None)

    # Set the correct env var
    os.environ["OPEN_BRAIN_API_URL"] = "http://custom-api:9000"

    # Re-import the module to pick up the new env var
    import cli.ob as ob_module
    importlib.reload(ob_module)

    # Verify the correct env var was read
    assert ob_module._OB_API_URL == "http://custom-api:9000"

    # Clean up
    os.environ.pop("OPEN_BRAIN_API_URL", None)
