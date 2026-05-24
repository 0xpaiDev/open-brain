.PHONY: help start stop up down migrate db-shell test lint format clean logs logs-api logs-worker check-config check-env memory-state memory-distill memory-curate memory-logs memory-tail memory-clean-logs memory-install-cron memory-uninstall-cron

help:
	@echo "Open Brain Makefile"
	@echo ""
	@echo "Local (WSL2 / no Docker):"
	@echo "  make start           - Start API and worker locally"
	@echo "  make stop            - Stop all local processes"
	@echo "  make logs            - Tail API and worker logs"
	@echo "  make logs-api        - Tail API log"
	@echo "  make logs-worker     - Tail worker log"
	@echo ""
	@echo "Docker:"
	@echo "  make up              - Start services via docker compose (api, worker, scheduler)"
	@echo "  make down            - Stop docker compose services"
	@echo "  make job-status      - Check scheduled job status (requires API_KEY env var)"
	@echo ""
	@echo "Database:"
	@echo "  make migrate         - Run Alembic migrations (alembic upgrade head)"
	@echo "  make db-shell        - Open psql shell to Supabase database"
	@echo ""
	@echo "Dev:"
	@echo "  make test            - Run full test suite"
	@echo "  make test-watch      - Run tests, stop on first failure"
	@echo "  make lint            - ruff + black --check + mypy"
	@echo "  make format          - Auto-format with black and ruff"
	@echo "  make check-config    - Validate all config variables are used"
	@echo "  make check-env       - Validate env vars are consistent"
	@echo "  make clean           - Remove __pycache__, .pytest_cache, etc."
	@echo ""
	@echo "Memory flywheel:"
	@echo "  make memory-state         - Show last-distill, pending sessions, file sizes vs caps"
	@echo "  make memory-distill       - Run daily memory distillation on demand"
	@echo "  make memory-curate        - Run weekly memory curator on demand"
	@echo "  make memory-logs          - Show recent distill/curate run summaries"
	@echo "  make memory-tail          - Live-tail the distill and curate logs"
	@echo "  make memory-clean-logs    - Truncate /tmp/ob-memory-*.log files"
	@echo "  make memory-install-cron  - Install anacron entries for daily/weekly runs"
	@echo "  make memory-uninstall-cron- Remove the anacron entries"

# ── Local run (no Docker) ─────────────────────────────────────────────────────

start:
	@bash start.sh

stop:
	@bash stop.sh

logs:
	@tail -f /tmp/ob-api.log /tmp/ob-worker.log

logs-api:
	@tail -f /tmp/ob-api.log

logs-worker:
	@tail -f /tmp/ob-worker.log

# ── Docker ────────────────────────────────────────────────────────────────────

up:
	docker compose --profile api --profile worker --profile scheduler up -d
	@echo "Services started. Run 'make migrate' to apply Alembic migrations to Supabase."

down:
	docker compose --profile api --profile worker --profile scheduler down

job-status:
	@curl -s -H "X-API-Key: $${API_KEY}" http://localhost:8000/v1/jobs/status | python3 -m json.tool

migrate:
	@if [ -z "$$SQLALCHEMY_URL" ]; then \
		echo "Error: SQLALCHEMY_URL environment variable is not set."; \
		echo "Set it in your shell or .env file, then run: make migrate"; \
		exit 1; \
	fi
	alembic upgrade head

db-shell:
	@if [ -z "$$SQLALCHEMY_URL" ]; then \
		echo "Error: SQLALCHEMY_URL environment variable is not set."; \
		echo "Set it in your shell or .env file, then run: make db-shell"; \
		exit 1; \
	fi
	psql "$$SQLALCHEMY_URL"

test:
	pytest tests/ -v --tb=short

test-watch:
	pytest tests/ -v --tb=short -x

lint:
	ruff check src/ tests/
	black --check src/ tests/
	mypy src/

format:
	ruff check --fix src/ tests/
	black src/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name .coverage -delete
	find . -type d -name htmlcov -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +

check-config:
	python3 scripts/check_config.py

check-env:
	python3 scripts/check_env_consistency.py

# ── Memory flywheel ───────────────────────────────────────────────────────────

memory-state:
	@python3 scripts/memory/state.py

memory-distill:
	@ANTHROPIC_API_KEY= bash scripts/memory/run-distill.sh

memory-curate:
	@ANTHROPIC_API_KEY= bash scripts/memory/run-curate.sh

memory-logs:
	@echo "==== distill (last 5) ===="
	@grep -E '^==== .* (start|done) ' /tmp/ob-memory-distill.log 2>/dev/null | tail -10 || echo "(no log)"
	@echo
	@echo "==== curate (last 5) ===="
	@grep -E '^==== .* (start|done) ' /tmp/ob-memory-curate.log 2>/dev/null | tail -10 || echo "(no log)"

memory-tail:
	@tail -f /tmp/ob-memory-distill.log /tmp/ob-memory-curate.log

memory-clean-logs:
	@for f in /tmp/ob-memory-distill.log /tmp/ob-memory-curate.log; do \
		if [ -f "$$f" ]; then : > "$$f"; echo "truncated $$f"; fi \
	done

memory-install-cron:
	@bash scripts/memory/install-anacron.sh

memory-uninstall-cron:
	@bash scripts/memory/install-anacron.sh --uninstall

