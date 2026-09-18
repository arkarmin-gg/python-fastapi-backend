.PHONY: help install run migrate makemigration downgrade seed clear-db test lint format

help:
	@echo "python-fastapi-backend — common tasks"
	@echo "  make install         Install dependencies (uv sync)"
	@echo "  make run             Run the API with autoreload"
	@echo "  make migrate         Apply migrations (alembic upgrade head)"
	@echo "  make makemigration m=\"msg\"   Autogenerate a migration"
	@echo "  make downgrade       Revert the last migration"
	@echo "  make seed            Seed demo organization + owner user"
	@echo "  make clear-db        Clear all application data (requires confirm=yes)"
	@echo "  make test            Run unit tests"
	@echo "  make lint            Check lint + format (no changes)"
	@echo "  make format          Auto-fix lint + format"

install:
	uv sync

run:
	uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8003

migrate:
	uv run alembic upgrade head

makemigration:
	uv run alembic revision --autogenerate -m "$(m)"

downgrade:
	uv run alembic downgrade -1

seed:
	uv run python -m scripts.seed

clear-db:
	@if [ "$(confirm)" != "yes" ]; then \
		echo "Refusing to clear database. Run: make clear-db confirm=yes"; \
		exit 1; \
	fi
	uv run python -m scripts.clear_database --yes

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff check --fix src tests
	uv run ruff format src tests
