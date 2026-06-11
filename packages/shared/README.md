# harnext-shared

Shared Python types used by `apps/api` and `apps/worker`. Three small modules:

- `envelope.py` — `CloudEvent` Pydantic model. The single normalization point.
- `pipeline.py` — `IngestionContext`, `Processor`, `Sink` protocols. The worker contract.
- `topics.py` — Kafka topic name constants and helpers.

This package has **no I/O** — no Kafka client, no DB, no HTTP. Pure types and protocols. Heavier code lives in the apps that import them.
