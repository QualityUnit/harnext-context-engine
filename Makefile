.PHONY: help up down logs ps install bootstrap api worker web clean fmt lint typecheck test smoke

help:
	@echo "Infra:"
	@echo "  make up         — start FalkorDB + Redpanda + MinIO"
	@echo "  make down       — stop infra"
	@echo "  make logs       — tail infra logs"
	@echo "  make ps         — status of infra containers"
	@echo ""
	@echo "Dev:"
	@echo "  make install    — install Python (uv) and JS (pnpm) deps"
	@echo "  make bootstrap  — create DB tables, ensure MinIO bucket, seed default tenant"
	@echo "  make api        — run the Ingest API (FastAPI) on :8000"
	@echo "  make worker     — run the ingestion worker"
	@echo "  make web        — run the Next.js dashboard on :3000"
	@echo "  make smoke      — POST a sample event via curl"
	@echo ""
	@echo "Quality:"
	@echo "  make fmt        — format Python (ruff)"
	@echo "  make lint       — lint Python (ruff) + JS (next lint)"
	@echo "  make typecheck  — pyright + tsc"
	@echo "  make test       — pytest"

up:
	docker compose -f infra/docker-compose.yml up -d

down:
	docker compose -f infra/docker-compose.yml down

logs:
	docker compose -f infra/docker-compose.yml logs -f

ps:
	docker compose -f infra/docker-compose.yml ps

install:
	uv sync
	pnpm install

bootstrap:
	uv run --package meaninggrid-api python -m meaninggrid_api.bootstrap

smoke:
	@echo "POST /api/v1/ingest …"
	curl -s -X POST http://localhost:8000/api/v1/ingest \
	  -H 'Content-Type: application/json' \
	  -H 'X-Tenant-Id: default' \
	  -d '{"source":"webhook:smoke","type":"smoke.test","subject":"smoke:1","data":{"hello":"world"}}' \
	  | python -m json.tool

api:
	uv run --package meaninggrid-api uvicorn meaninggrid_api.main:app --reload --host 0.0.0.0 --port 8000

worker:
	uv run --package meaninggrid-worker python -m meaninggrid_worker.main

web:
	pnpm --filter @meaninggrid/web dev --port 3100

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	pnpm --filter @meaninggrid/web lint

typecheck:
	uv run pyright
	pnpm --filter @meaninggrid/web typecheck

test:
	uv run pytest

clean:
	rm -rf .venv .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	pnpm --filter @meaninggrid/web exec rm -rf .next node_modules 2>/dev/null || true
