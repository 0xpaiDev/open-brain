.PHONY: help up down migrate db-shell test lint format clean

help:
	@echo "Open Brain Makefile"
	@echo ""
	@echo "Commands:"
	@echo "  make up              - Start all services (docker compose up -d)"
	@echo "  make down            - Stop all services (docker compose down)"
	@echo "  make migrate         - Run Alembic migrations (alembic upgrade head)"
	@echo "  make db-shell        - Open psql shell to the database"
	@echo "  make test            - Run pytest on all tests"
	@echo "  make test-watch      - Run pytest with -v and stop on first failure"
	@echo "  make lint            - Run ruff check + black --check + mypy"
	@echo "  make format          - Format code with black and ruff"
	@echo "  make clean           - Remove __pycache__, .pytest_cache, .coverage"
	@echo "  make logs-api        - Tail API service logs"
	@echo "  make logs-worker     - Tail worker service logs"
	@echo "  make logs-db         - Tail database service logs"

up:
	docker compose up -d
	@echo "Services started. Wait for db to be ready, then run 'make migrate'"

down:
	docker compose down

migrate:
	alembic upgrade head

db-shell:
	docker compose exec db psql -U openbrain -d openbrain

test:
	pytest tests/ -v --tb=short

test-watch:
	pytest tests/ -v --tb=short -x

lint:
	ruff check src/ tests/ cli/
	black --check src/ tests/ cli/
	mypy src/

format:
	ruff check --fix src/ tests/ cli/
	black src/ tests/ cli/

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

logs-db:
	docker compose logs -f db
