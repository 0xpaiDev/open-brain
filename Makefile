.PHONY: help up down migrate db-shell test lint format clean

help:
	@echo "Open Brain Makefile"
	@echo ""
	@echo "Commands:"
	@echo "  make up              - Start API and worker services (docker compose up -d)"
	@echo "  make down            - Stop all services (docker compose down)"
	@echo "  make migrate         - Run Alembic migrations (alembic upgrade head)"
	@echo "  make db-shell        - Open psql shell to Supabase database (requires SQLALCHEMY_URL)"
	@echo "  make test            - Run pytest on all tests"
	@echo "  make test-watch      - Run pytest with -v and stop on first failure"
	@echo "  make lint            - Run ruff check + black --check + mypy"
	@echo "  make format          - Format code with black and ruff"
	@echo "  make clean           - Remove __pycache__, .pytest_cache, .coverage"
	@echo "  make logs-api        - Tail API service logs"
	@echo "  make logs-worker     - Tail worker service logs"

up:
	docker compose up -d
	@echo "Services started. Run 'make migrate' to apply Alembic migrations to Supabase."

down:
	docker compose down

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

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker
