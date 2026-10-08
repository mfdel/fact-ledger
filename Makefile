# Developer commands. `make check` runs every gate that CI runs, except the slow
# LiteLLM tests (`pytest -m slow`), which only CI runs.
.DEFAULT_GOAL := help
UV := uv run
IMAGE ?= fact-ledger:dev

.PHONY: help install fmt lint type arch slim test cov audit eval check run migrate docker-build docker-run

help: ## Show targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install dependencies and git hooks
	uv sync --locked
	$(UV) pre-commit install --install-hooks

fmt: ## Format code and apply safe lint fixes
	$(UV) ruff format .
	$(UV) ruff check --fix .

lint: ## Lint and check formatting
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) codespell

type: ## Static type check (mypy strict)
	$(UV) mypy

arch: ## Check layer contracts (import-linter)
	$(UV) lint-imports

slim: ## Fail on dead code, tiny modules and comment-heavy files
	$(UV) python scripts/slim_check.py

test: ## Run tests in parallel
	$(UV) pytest -n auto

cov: ## Run tests with the coverage gate
	$(UV) pytest -n auto --cov --cov-report=term --cov-report=xml

audit: ## Scan dependencies for known vulnerabilities
	uv export --locked --no-dev --no-emit-project --format requirements-txt > .audit-requirements.txt
	$(UV) pip-audit --strict --disable-pip -r .audit-requirements.txt; status=$$?; rm -f .audit-requirements.txt; exit $$status

eval: ## Run the seeded-error evaluation
	$(UV) python -m evals.harness

check: lint type arch slim cov eval ## Run every quality gate

run: ## Run the web service with reload
	$(UV) fact-ledger serve --reload

migrate: ## Apply database migrations
	$(UV) alembic upgrade head

docker-build: ## Build the container image
	docker build -t $(IMAGE) .

docker-run: ## Run the container image on port 8000
	docker run --rm -p 8000:8000 $(IMAGE)
