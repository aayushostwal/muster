# Muster — local development
#
# Convenience wrapper around the "Local dev" flow in README.md. Nothing here
# runs in production — that's scripts/install.sh + musterctl. This is only
# for running the stack from a checkout on your own machine.

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend
VENV := $(BACKEND_DIR)/.venv
PYTHON := $(abspath $(VENV))/bin/python
PIP := $(abspath $(VENV))/bin/pip

.PHONY: help install backend-install frontend-install \
        up down db-up db-down logs \
        migrate migration dev-backend dev-frontend \
        test test-backend typecheck-frontend build-frontend \
        clean clean-backend clean-frontend

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

## --- Setup ------------------------------------------------------------

install: backend-install frontend-install ## Install backend (venv) + frontend (npm) deps

backend-install: ## Create backend/.venv and install requirements.txt into it
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r $(BACKEND_DIR)/requirements.txt

frontend-install: ## npm install the frontend
	cd $(FRONTEND_DIR) && npm install

## --- Docker (Postgres + frontend) --------------------------------------

up: ## Start Postgres + frontend containers
	docker compose up -d postgres frontend

db-up: ## Start only Postgres
	docker compose up -d postgres

down: ## Stop and remove all containers
	docker compose down

db-down: ## Stop only Postgres
	docker compose stop postgres

logs: ## Tail docker compose logs (all services)
	docker compose logs -f

## --- Backend -------------------------------------------------------------

migrate: ## Run Alembic migrations against the running Postgres
	cd $(BACKEND_DIR) && $(PYTHON) -m alembic upgrade head

migration: ## Generate a new empty Alembic revision (make migration name=add_x)
	cd $(BACKEND_DIR) && $(PYTHON) -m alembic revision -m "$(name)"

dev-backend: ## Run the backend with hot reload (needs `make up` + `make migrate` first)
	cd $(BACKEND_DIR) && $(PYTHON) -m uvicorn app.main:app --reload --port 8080

test-backend: ## Run backend tests (in-memory SQLite, no Postgres needed)
	cd $(BACKEND_DIR) && $(PYTHON) -m pytest

## --- Frontend --------------------------------------------------------

dev-frontend: ## Run the frontend dev server (http://localhost:5173)
	cd $(FRONTEND_DIR) && npm run dev

typecheck-frontend: ## Type-check the frontend without emitting
	cd $(FRONTEND_DIR) && npx tsc --noEmit

build-frontend: ## Production build of the frontend
	cd $(FRONTEND_DIR) && npm run build

## --- Aggregate ---------------------------------------------------------

test: test-backend typecheck-frontend ## Run backend tests + frontend type-check

## --- Cleanup -------------------------------------------------------------

clean: clean-backend clean-frontend ## Remove venv, node_modules, and caches

clean-backend: ## Remove backend/.venv and Python caches
	rm -rf $(VENV)
	find $(BACKEND_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND_DIR)/.pytest_cache

clean-frontend: ## Remove frontend node_modules and build output
	rm -rf $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist
