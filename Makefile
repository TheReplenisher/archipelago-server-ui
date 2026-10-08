# Developer shortcuts. Needs uv and Node.js (see CONTRIBUTING.md).
.PHONY: install dev-backend dev-frontend build lint format test check

DEV_DATA := $(CURDIR)/.dev-data

install:
	cd backend && uv sync
	cd frontend && npm ci

# API on :8000. Serves frontend/dist too, if it has been built.
dev-backend:
	cd backend && APSUI_DATA_DIR=$(DEV_DATA) uv run uvicorn apsui.main:create_app --factory --reload --port 8000

# Vite on :5173 with hot reload, forwarding /api to dev-backend.
dev-frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd frontend && npm run lint && npm run format:check && npm run typecheck

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format

test:
	cd backend && uv run pytest
	cd frontend && npm test

check: lint test
