install:
	uv sync

run:
	@uv run python -m src

debug:
	uv run python -m pdb -m src

clean:
	@find . -name __pycache__ -not -path "./.venv/*" -prune -exec rm -rf {} +
	@rm -rf .mypy_cache .pytest_cache data/processed

fclean: clean
	@rm -rf .venv

lint:
	uv run flake8 .
	uv run mypy . --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict:
	uv run flake8 .
	uv run mypy . --strict

.PHONY: install run debug test clean fclean lint lint-strict
