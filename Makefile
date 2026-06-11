.PHONY: help up down logs ps install topics ingest classifier builder mcp web worker beat fmt lint typecheck test clean

help:
	@echo "Infra:"
	@echo "  make up         — start Redpanda (Kafka) + Redis (Celery broker)"
	@echo "  make down       — stop infra"
	@echo "  make logs       — tail infra logs"
	@echo "  make ps         — status of infra containers"
	@echo "  make topics     — create the cms.events.* topics"
	@echo ""
	@echo "Dev (run each in its own shell):"
	@echo "  make ingest     — Ingest API + connectors (FastAPI) on :8000"
	@echo "  make classifier — fast/batch router"
	@echo "  make builder    — AgentFS builder consumer"
	@echo "  make mcp         — MCP context server on :8765"
	@echo "  make web        — Next.js source-connection UI on :3100"
	@echo "  make worker     — Celery worker (source polls + sitemap crawl)"
	@echo "  make beat       — Celery beat (schedules polls every minute)"
	@echo ""
	@echo "Quality:"
	@echo "  make install    — uv sync + pnpm install"
	@echo "  make fmt / lint / typecheck / test"

up:
	docker compose -f infra/docker-compose.yml up -d

down:
	docker compose -f infra/docker-compose.yml down

logs:
	docker compose -f infra/docker-compose.yml logs -f

ps:
	docker compose -f infra/docker-compose.yml ps

# Create the three lane topics (idempotent). fast=50 parts, batch=30, raw=50.
topics:
	docker exec harnext-redpanda rpk topic create cms.events.raw.v1   -p 50 -r 1 || true
	docker exec harnext-redpanda rpk topic create cms.events.fast.v1  -p 50 -r 1 || true
	docker exec harnext-redpanda rpk topic create cms.events.batch.v1 -p 30 -r 1 || true
	docker exec harnext-redpanda rpk topic list

install:
	uv sync
	pnpm install

ingest:
	uv run --package harnext-ingest uvicorn harnext_ingest.main:app --reload --host 0.0.0.0 --port 8000

classifier:
	uv run --package harnext-classifier python -m harnext_classifier.main

builder:
	uv run --package harnext-builder python -m harnext_builder.main

mcp:
	uv run --package harnext-mcp python -m harnext_mcp.main

web:
	pnpm --filter @harnext/web dev --port 3100

worker:
	uv run --package harnext-ingest celery -A harnext_ingest.celery_app worker --loglevel=info --concurrency=2

beat:
	uv run --package harnext-ingest celery -A harnext_ingest.celery_app beat --loglevel=info

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .

typecheck:
	uv run pyright

test:
	uv run pytest

clean:
	rm -rf .venv .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
