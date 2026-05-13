"""Ingest API + read API entrypoint.

See docs/architecture/ingestion-pipeline.md §6 (ingest) and dashboard.md §6 (reads).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from meaninggrid_api.db import init_models
from meaninggrid_api.graphiti_client import start_graphiti, stop_graphiti
from meaninggrid_api.kafka import start_producer, stop_producer
from meaninggrid_api.routes import documents, events, graph, ingest
from meaninggrid_api.settings import settings
from meaninggrid_api.storage import ensure_bucket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("meaninggrid.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("api booting")
    await init_models()
    await ensure_bucket()
    await start_producer()
    await start_graphiti()
    log.info("api ready")
    try:
        yield
    finally:
        log.info("api shutting down")
        await stop_producer()
        await stop_graphiti()


app = FastAPI(
    title="meaninggrid API",
    version="0.0.1",
    description="Ingest API + read API. See docs/architecture/.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3100"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(events.router)
app.include_router(graph.router)
app.include_router(documents.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    import uvicorn

    uvicorn.run(
        "meaninggrid_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
