.PHONY: install install-hooks test lint format demo clean

install:
	uv sync --extra dev

install-hooks:
	./scripts/install-hooks.sh

test:
	uv run pytest

coverage:
	uv run pytest --cov=janus --cov-report=term-missing

schema:
	uv run janus schema check

lint:
	uv run ruff check .
	uv run mypy core/janus || true

format:
	uv run ruff format .
	uv run ruff check --fix .

demo:
	uv run janus demo

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
