# apps/worker — Ingestion worker

Async Python worker. Consumes `events.raw.v1` from Kafka, runs the processor chain (Phase A), then fans out to sinks (Phase B). v0 ships with a single sink: **GraphitiSink**.

See [`docs/architecture/ingestion-pipeline.md` §9](../../docs/architecture/ingestion-pipeline.md) for the full architecture.

## Run (dev)

```bash
make worker     # from repo root
```

Or directly:

```bash
uv run --package meaninggrid-worker python -m meaninggrid_worker.main
```

## Layout

```
src/meaninggrid_worker/
├── main.py          — entrypoint (Kafka loop)
├── pipeline.py      — build_chain (processors) + run_sinks
├── settings.py      — env-driven config
├── processors/      — Phase A (currently empty)
└── sinks/
    └── graphiti.py  — Phase B, v0 sink (currently stub)
```

## Adding a processor or sink

The recipes are in [`docs/architecture/ingestion-pipeline.md`](../../docs/architecture/ingestion-pipeline.md) §9.7 (processor) and §9.8 (sink). Both are one-file changes; adding a sink should never require touching processors or other sinks. If it does, the design is being violated — push back.
