# ProtoForge Makefile
# Quick start: make install && make demo
# Run tests: make test
# Docker: make docker-up

.PHONY: install install-dev run demo stop test test-unit test-smoke lint type-check format docker-build docker-up docker-down docker-logs clean help

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install ProtoForge for production
	pip install -e ".[all]"

install-dev: ## Install ProtoForge with development dependencies
	pip install -e ".[dev,all]"

run: ## Start ProtoForge server
	python -m protoforge.cli run

demo: ## Start ProtoForge in demo mode (with sample devices)
	python -m protoforge.cli demo

stop: ## Stop background daemon
	python -m protoforge.cli stop

test: ## Run all tests
	python -m pytest tests/ -v --tb=short

test-unit: ## Run unit tests only
	python -m pytest tests/test_behavior_models.py tests/test_state_machine.py tests/test_generator.py tests/test_integration.py tests/test_log_bus.py tests/test_api.py -v --tb=short

test-smoke: ## Run E2E smoke tests (starts server automatically)
	python scripts/smoke_test.py

lint: ## Run Ruff linter
	ruff check protoforge/ tests/ scripts/

format: ## Auto-format code with Ruff
	ruff check --fix protoforge/ tests/ scripts/
	ruff format protoforge/ tests/ scripts/

type-check: ## Run MyPy type checker
	mypy protoforge/ --ignore-missing-imports

docker-build: ## Build Docker image
	docker build -t protoforge:latest .

docker-up: ## Start ProtoForge with Docker Compose (simple mode)
	docker compose -f docker-compose.simple.yml up -d

docker-down: ## Stop Docker Compose services
	docker compose -f docker-compose.simple.yml down

docker-logs: ## Show Docker logs
	docker compose -f docker-compose.simple.yml logs -f

clean: ## Clean build artifacts and caches
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
