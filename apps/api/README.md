# apps/api — Ingest API

Thin FastAPI service. Single responsibility: get events into Kafka safely.

See [`docs/architecture/ingestion-pipeline.md` §6](../../docs/architecture/ingestion-pipeline.md) for the design.

## Run (dev)

```bash
make api    # from repo root
```

Or directly:

```bash
uv run --package meaninggrid-api uvicorn meaninggrid_api.main:app --reload --port 8000
```

## Endpoints (v0 stubs)

| Method | Path        | Returns | Notes |
|--------|-------------|---------|-------|
| GET    | `/healthz`  | 200     | Liveness check |
| POST   | `/ingest`   | 202     | Accepts a CloudEvent payload. Currently a stub — does not yet publish to Kafka. |
| GET    | `/docs`     | Swagger UI | Auto-generated from FastAPI |
