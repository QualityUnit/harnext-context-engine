"""Ingest API — accounts, projects, OAuth connect, source sync. Serves the UI."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from meaninggrid_shared import (
    BuildLedger,
    IngestedEvent,
    Project,
    Source,
    User,
    init_db,
    make_engine,
    make_sessionmaker,
)

from meaninggrid_ingest import oauth
from meaninggrid_ingest.connectors import SUPPORTED_KINDS
from meaninggrid_ingest.kafka import Producer
from meaninggrid_ingest.schemas import (
    BuildOut,
    ChannelOut,
    EventOut,
    LoginIn,
    ProjectCreate,
    ProjectOut,
    RepoOut,
    SourceCreate,
    SourceOut,
    SyncOut,
    UserOut,
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
    app.state.settings = settings
    app.state.service = SourceService(make_sessionmaker(engine), producer, settings)
    try:
        yield
    finally:
        await producer.stop()
        await engine.dispose()


_BOOT = IngestSettings()
app = FastAPI(title="MeaningGrid Ingest", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_BOOT.web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


def service() -> SourceService:
    return app.state.service


def settings() -> IngestSettings:
    return app.state.settings


SvcDep = Annotated[SourceService, Depends(service)]
CfgDep = Annotated[IngestSettings, Depends(settings)]


def _project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        owner_id=p.owner_id,
        created_at=p.created_at,
        github_login=p.github_login,
        github_connected=bool(p.github_token),
        slack_team_name=p.slack_team_name,
        slack_connected=bool(p.slack_token),
    )


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
async def health(cfg: CfgDep) -> dict:
    return {
        "ok": True,
        "kinds": list(SUPPORTED_KINDS),
        "oauth": {
            "github": bool(cfg.github_oauth_client_id),
            "slack": bool(cfg.slack_oauth_client_id),
        },
    }


# -- auth ------------------------------------------------------------------
@app.post("/auth/login", response_model=UserOut)
async def login(body: LoginIn, svc: SvcDep) -> User:
    if not body.username.strip():
        raise HTTPException(400, "username required")
    return await svc.login(body.username.strip())


# -- projects --------------------------------------------------------------
@app.post("/projects", response_model=ProjectOut)
async def create_project(body: ProjectCreate, svc: SvcDep) -> ProjectOut:
    return _project_out(await svc.create_project(body.owner_id, body.name))


@app.get("/projects", response_model=list[ProjectOut])
async def list_projects(svc: SvcDep, owner_id: Annotated[str, Query()]) -> list[ProjectOut]:
    return [_project_out(p) for p in await svc.list_projects(owner_id)]


@app.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, svc: SvcDep) -> ProjectOut:
    p = await svc.get_project(project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return _project_out(p)


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, svc: SvcDep) -> dict:
    if not await svc.delete_project(project_id):
        raise HTTPException(404, "project not found")
    return {"deleted": project_id}


# -- OAuth connect ---------------------------------------------------------
def _creds(provider: str, cfg: IngestSettings) -> tuple[str | None, str | None]:
    if provider == "github":
        return cfg.github_oauth_client_id, cfg.github_oauth_client_secret
    if provider == "slack":
        return cfg.slack_oauth_client_id, cfg.slack_oauth_client_secret
    return None, None


@app.get("/oauth/{provider}/start")
async def oauth_start(
    provider: str, svc: SvcDep, cfg: CfgDep, project_id: Annotated[str, Query()]
) -> RedirectResponse:
    if provider not in ("github", "slack"):
        raise HTTPException(404, "unknown provider")
    client_id, _ = _creds(provider, cfg)
    if not client_id:
        return RedirectResponse(
            f"{cfg.web_origin}/projects/{project_id}?error=oauth_not_configured"
        )
    if await svc.get_project(project_id) is None:
        raise HTTPException(404, "project not found")
    state = oauth.new_state(project_id, provider)
    redirect = oauth.redirect_uri(cfg.oauth_redirect_base, provider)
    url = (
        oauth.github_authorize_url(client_id, redirect, state)
        if provider == "github"
        else oauth.slack_authorize_url(client_id, redirect, state)
    )
    return RedirectResponse(url)


@app.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    svc: SvcDep,
    cfg: CfgDep,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> RedirectResponse:
    parsed = oauth.consume_state(state)
    if parsed is None or parsed[1] != provider:
        raise HTTPException(400, "invalid or expired OAuth state")
    project_id = parsed[0]
    client_id, client_secret = _creds(provider, cfg)
    if not client_id or not client_secret:
        raise HTTPException(400, "oauth not configured")
    redirect = oauth.redirect_uri(cfg.oauth_redirect_base, provider)
    try:
        if provider == "github":
            res = await oauth.github_exchange(client_id, client_secret, code, redirect)
            await svc.set_github_token(project_id, res["login"], res["token"])
        else:
            res = await oauth.slack_exchange(client_id, client_secret, code, redirect)
            await svc.set_slack_token(project_id, res["team_id"], res["team_name"], res["token"])
    except Exception as e:
        return RedirectResponse(f"{cfg.web_origin}/projects/{project_id}?error={type(e).__name__}")
    return RedirectResponse(f"{cfg.web_origin}/projects/{project_id}?connected={provider}")


@app.get("/oauth/github/repos", response_model=list[RepoOut])
async def github_repos(svc: SvcDep, project_id: Annotated[str, Query()]) -> list[dict]:
    p = await svc.get_project(project_id)
    if p is None or not p.github_token:
        raise HTTPException(400, "GitHub not connected for this project")
    return await oauth.github_list_repos(p.github_token)


@app.get("/oauth/slack/channels", response_model=list[ChannelOut])
async def slack_channels(svc: SvcDep, project_id: Annotated[str, Query()]) -> list[dict]:
    p = await svc.get_project(project_id)
    if p is None or not p.slack_token:
        raise HTTPException(400, "Slack not connected for this project")
    return await oauth.slack_list_channels(p.slack_token)


# -- sources ---------------------------------------------------------------
@app.post("/sources", response_model=SourceOut)
async def create_source(body: SourceCreate, svc: SvcDep) -> SourceOut:
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(400, f"unsupported kind {body.kind!r}")
    try:
        src = await svc.create_source(body.project_id, body.kind, body.config, body.secret)
    except KeyError:
        raise HTTPException(404, "project not found") from None
    return _source_out(src)


@app.get("/sources", response_model=list[SourceOut])
async def list_sources(
    svc: SvcDep, project_id: Annotated[str | None, Query()] = None
) -> list[SourceOut]:
    return [_source_out(s) for s in await svc.list_sources(project_id)]


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
    svc: SvcDep, project_id: Annotated[str, Query()], limit: Annotated[int, Query(le=500)] = 50
) -> list[IngestedEvent]:
    return await svc.list_events(project_id, limit)


@app.get("/builds", response_model=list[BuildOut])
async def list_builds(
    svc: SvcDep, project_id: Annotated[str, Query()], limit: Annotated[int, Query(le=500)] = 50
) -> list[BuildLedger]:
    return await svc.list_builds(project_id, limit)


def run() -> None:
    import uvicorn

    s = IngestSettings()
    uvicorn.run("meaninggrid_ingest.main:app", host=s.api_host, port=s.api_port, reload=False)


if __name__ == "__main__":
    run()
