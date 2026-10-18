# Contributing to Dockseed

Thank you for your interest in contributing to Dockseed!

## Development Setup

Dockseed uses **Poetry** for dependency management and packaging.

~~~bash
git clone https://github.com/your-org/dockseed.git
cd dockseed
poetry env use 3.11
poetry install
~~~

## Quality Gates

Before submitting a Pull Request, ensure all static checks and tests pass locally:

~~~bash
# 1. Format and lint with Ruff
poetry run ruff format --check src/ tests/
poetry run ruff check src/ tests/

# 2. Strict type checking with Mypy
poetry run mypy --strict src/ tests/

# 3. Run unit tests with >= 95% coverage
poetry run pytest -m "not integration" --cov=dockseed --cov-report=term-missing --cov-fail-under=95

# 4. Verify package build
poetry check
poetry build
~~~
