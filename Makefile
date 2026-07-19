.PHONY: dev test lint fmt

dev:
	uv run wingman serve --reload

test:
	uv run pytest

lint:
	uv run ruff format --check .
	uv run ruff check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .
