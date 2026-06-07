"""Ingest API — source registration + connector sync. Serves the web UI."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from meaninggrid_shared import (
    BuildLedger,
    IngestedEvent,
    Org,
    Source,
    init_db,
    make_engine,
    make_sessionmaker,
)

from meaninggrid_ingest.connectors import SUPPORTED_KINDS
from meaninggrid_ingest.kafka import Producer
from meaninggrid_ingest.schemas import (
    BuildOut,
    EventOut,
    OrgCreate,
    OrgOut,
    SourceCreate,
    SourceOut,
    SyncOut,
)
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = IngestSettings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    producer = Producer(settings.kafka_bootstrap_servers)
    await producer.start()
    app.state.service = SourceService(make_sessionmaker(engine), producer, settings)
    try:
        yield
    finally:
        await producer.stop()
        await engine.dispose()


def _settings() -> IngestSettings:
    return IngestSettings()


app = FastAPI(title="MeaningGrid Ingest", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings().web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


def service() -> SourceService:
    return app.state.service


SvcDep = Annotated[SourceService, Depends(service)]


def _source_out(src: Source) -> SourceOut:
    return SourceOut(
        id=src.id,
        org_id=src.org_id,
        kind=src.kind,
        config=json.loads(src.config_json),
        status=src.status,
        cursor=src.cursor,
        last_sync_at=src.last_sync_at,
        last_error=src.last_error,
        created_at=src.created_at,
        has_secret=bool(src.secret),
    )


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "kinds": list(SUPPORTED_KINDS)}


@app.get("/orgs", response_model=list[OrgOut])
async def list_orgs(svc: SvcDep) -> list[Org]:
    return await svc.list_orgs()


@app.post("/orgs", response_model=OrgOut)
async def create_org(body: OrgCreate, svc: SvcDep) -> Org:
    return await svc.ensure_org(body.id, body.name)


@app.post("/sources", response_model=SourceOut)
async def create_source(body: SourceCreate, svc: SvcDep) -> SourceOut:
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(400, f"unsupported kind {body.kind!r}; one of {SUPPORTED_KINDS}")
    if body.org_name:
        await svc.ensure_org(body.org_id, body.org_name)
    src = await svc.create_source(body.org_id, body.kind, body.config, body.secret)
    return _source_out(src)


@app.get("/sources", response_model=list[SourceOut])
async def list_sources(
    svc: SvcDep, org_id: Annotated[str | None, Query()] = None
) -> list[SourceOut]:
    return [_source_out(s) for s in await svc.list_sources(org_id)]


@app.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(source_id: str, svc: SvcDep) -> SourceOut:
    src = await svc.get_source(source_id)
    if src is None:
        raise HTTPException(404, "source not found")
    return _source_out(src)


@app.delete("/sources/{source_id}")
async def delete_source(source_id: str, svc: SvcDep) -> dict:
    if not await svc.delete_source(source_id):
        raise HTTPException(404, "source not found")
    return {"deleted": source_id}


@app.post("/sources/{source_id}/sync", response_model=SyncOut)
async def sync_source(source_id: str, svc: SvcDep) -> SyncOut:
    try:
        n = await svc.sync(source_id)
    except KeyError:
        raise HTTPException(404, "source not found") from None
    except Exception as e:
        raise HTTPException(502, f"sync failed: {e}") from e
    return SyncOut(source_id=source_id, ingested=n)


@app.get("/events", response_model=list[EventOut])
async def list_events(
    svc: SvcDep,
    org_id: Annotated[str, Query()],
    limit: Annotated[int, Query(le=500)] = 50,
) -> list[IngestedEvent]:
    return await svc.list_events(org_id, limit)


@app.get("/builds", response_model=list[BuildOut])
async def list_builds(
    svc: SvcDep,
    org_id: Annotated[str, Query()],
    limit: Annotated[int, Query(le=500)] = 50,
) -> list[BuildLedger]:
    return await svc.list_builds(org_id, limit)


def run() -> None:
    import uvicorn

    s = IngestSettings()
    uvicorn.run("meaninggrid_ingest.main:app", host=s.api_host, port=s.api_port, reload=False)


if __name__ == "__main__":
    run()
