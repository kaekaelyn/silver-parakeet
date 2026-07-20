.PHONY: dev test lint init-db

dev:
	uv run uvicorn wingman.web.app:app --reload --host 127.0.0.1 --port 8484

init-db:
	uv run wingman init-db

test:
	uv run pytest

lint:
	uv run ruff format --check .
	uv run ruff check .
