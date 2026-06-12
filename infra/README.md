# infra

Local-dev infrastructure for harnext. One `docker-compose.yml` brings up the three services the architecture needs.

## Services

| Service    | Image                       | Ports                                       | Purpose                                                   |
|------------|-----------------------------|---------------------------------------------|-----------------------------------------------------------|
| Redpanda   | `redpandadata/redpanda`     | `9092` Kafka, `8082` HTTP proxy, `9644` admin | Kafka-compatible event log (single binary, no Zookeeper) |
| FalkorDB   | `falkordb/falkordb`         | `6379` Redis, `3001` Browser                 | Graph store backing Graphiti                              |
| MinIO      | `minio/minio`               | `9000` S3, `9001` console                    | Object storage for blobs (PDFs, audio, etc.)              |

## Run

```bash
make up         # docker compose -f infra/docker-compose.yml up -d
make ps         # status
make logs       # tail
make down       # stop
```

## What's intentionally NOT here

- **No SQLite container.** SQLite is a file inside the API/worker process; no separate service.
- **No Graphiti container.** Graphiti is a Python library used by `apps/worker` (and `apps/api` for reads); not its own service.
- **No app containers.** During dev you run apps natively (`make api`, `make worker`, `make web`) for fast feedback. Production Dockerfiles live alongside each app.

## Healthchecks

All three services have healthchecks. `make up` returns immediately; use `make ps` to check `healthy` status before connecting.

## Browser UIs

- **MinIO console**: <http://localhost:9001> (login: `harnext` / `harnext_dev`).
- **FalkorDB Browser**: <http://localhost:3001> — useful for inspecting raw graph during dev. Note the dashboard at <http://localhost:3000> shows the *semantic* graph; Browser shows the *raw* graph DB.
