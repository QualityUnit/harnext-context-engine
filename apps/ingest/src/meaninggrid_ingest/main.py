"""Ingest API — auth (email/password + Google), projects, OAuth connect, sync."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from meaninggrid_shared import (
    BuildLedger,
    IngestedEvent,
    Project,
    Source,
    User,
    create_mcp_token,
    init_db,
    make_engine,
    make_sessionmaker,
    migrate_schema,
)

from meaninggrid_ingest import oauth
from meaninggrid_ingest.connectors import SUPPORTED_KINDS
from meaninggrid_ingest.kafka import Producer
from meaninggrid_ingest.schemas import (
    AnalyticsOut,
    AuthOut,
    BuildOut,
    ChannelOut,
    EventOut,
    LoginIn,
    McpInfoOut,
    ProjectCreate,
    ProjectOut,
    ProjectRename,
    RegisterIn,
    RepoOut,
    SourceCreate,
    SourceOut,
    SyncOut,
    UserOut,
)
from meaninggrid_ingest.security import create_token, decode_token
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = IngestSettings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    await migrate_schema(engine)
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


async def current_user(
    svc: SvcDep, cfg: CfgDep, authorization: Annotated[str | None, Header()] = None
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    uid = decode_token(authorization[7:], cfg.jwt_secret)
    if not uid:
        raise HTTPException(401, "invalid or expired token")
    user = await svc.get_user(uid)
    if user is None:
        raise HTTPException(401, "user not found")
    return user


UserDep = Annotated[User, Depends(current_user)]


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id, email=u.email, name=u.name, avatar_url=u.avatar_url, created_at=u.created_at
    )


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


def _source_out(s: Source, event_count: int = 0) -> SourceOut:
    return SourceOut(
        id=s.id,
        org_id=s.org_id,
        kind=s.kind,
        config=json.loads(s.config_json),
        status=s.status,
        cursor=s.cursor,
        last_sync_at=s.last_sync_at,
        last_error=s.last_error,
        created_at=s.created_at,
        has_secret=bool(s.secret),
        event_count=event_count,
    )


async def _owned_project(svc: SourceService, user: User, project_id: str) -> Project:
    p = await svc.get_project(project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    if p.owner_id != user.id:
        raise HTTPException(403, "not your project")
    return p


async def _owned_source(svc: SourceService, user: User, source_id: str) -> Source:
    src = await svc.get_source(source_id)
    if src is None:
        raise HTTPException(404, "source not found")
    await _owned_project(svc, user, src.org_id)
    return src


def _token(cfg: IngestSettings, user: User) -> str:
    return create_token(user.id, cfg.jwt_secret, cfg.jwt_expiry_hours)


@app.get("/health")
async def health(cfg: CfgDep) -> dict:
    return {
        "ok": True,
        "kinds": list(SUPPORTED_KINDS),
        "oauth": {
            "github": bool(cfg.github_oauth_client_id),
            "slack": bool(cfg.slack_oauth_client_id),
            "google": bool(cfg.google_oauth_client_id),
        },
    }


# -- auth ------------------------------------------------------------------
@app.post("/auth/register", response_model=AuthOut)
async def register(body: RegisterIn, svc: SvcDep, cfg: CfgDep) -> AuthOut:
    if not cfg.registration_open:
        raise HTTPException(403, "registration is closed — this instance is invite-only")
    if "@" not in body.email or len(body.password) < 6:
        raise HTTPException(400, "valid email and a 6+ char password required")
    try:
        user = await svc.register(body.email.strip().lower(), body.password, body.name)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return AuthOut(token=_token(cfg, user), user=_user_out(user))


@app.post("/auth/login", response_model=AuthOut)
async def login(body: LoginIn, svc: SvcDep, cfg: CfgDep) -> AuthOut:
    user = await svc.authenticate(body.email.strip().lower(), body.password)
    if user is None:
        raise HTTPException(401, "invalid email or password")
    return AuthOut(token=_token(cfg, user), user=_user_out(user))


@app.get("/auth/me", response_model=UserOut)
async def me(user: UserDep) -> UserOut:
    return _user_out(user)


@app.get("/auth/google/start")
async def google_start(svc: SvcDep, cfg: CfgDep) -> RedirectResponse:
    if not cfg.google_oauth_client_id:
        return RedirectResponse(f"{cfg.web_origin}/login?error=google_not_configured")
    state = oauth.new_state("", "google")
    redirect = f"{cfg.oauth_redirect_base}/auth/google/callback"
    return RedirectResponse(oauth.google_authorize_url(cfg.google_oauth_client_id, redirect, state))


@app.get("/auth/google/callback")
async def google_callback(
    svc: SvcDep, cfg: CfgDep, code: Annotated[str, Query()], state: Annotated[str, Query()]
) -> RedirectResponse:
    parsed = oauth.consume_state(state)
    if parsed is None or parsed[1] != "google":
        raise HTTPException(400, "invalid or expired OAuth state")
    if not cfg.google_oauth_client_id or not cfg.google_oauth_client_secret:
        raise HTTPException(400, "google oauth not configured")
    redirect = f"{cfg.oauth_redirect_base}/auth/google/callback"
    try:
        info = await oauth.google_exchange(
            cfg.google_oauth_client_id, cfg.google_oauth_client_secret, code, redirect
        )
        user = await svc.upsert_google_user(
            info["sub"], info["email"], info["name"], info["picture"]
        )
    except Exception as e:  # noqa: BLE001
        return RedirectResponse(f"{cfg.web_origin}/login?error={type(e).__name__}")
    return RedirectResponse(f"{cfg.web_origin}/auth/callback?token={_token(cfg, user)}")


@app.get("/auth/github/start")
async def github_login_start(cfg: CfgDep) -> RedirectResponse:
    if not cfg.github_oauth_client_id:
        return RedirectResponse(f"{cfg.web_origin}/login?error=github_not_configured")
    state = oauth.new_state("", "github_login")
    redirect = f"{cfg.oauth_redirect_base}/auth/github/callback"
    return RedirectResponse(
        oauth.github_login_authorize_url(cfg.github_oauth_client_id, redirect, state)
    )


@app.get("/auth/github/callback")
async def github_login_callback(
    svc: SvcDep, cfg: CfgDep, code: Annotated[str, Query()], state: Annotated[str, Query()]
) -> RedirectResponse:
    parsed = oauth.consume_state(state)
    if parsed is None or parsed[1] != "github_login":
        raise HTTPException(400, "invalid or expired OAuth state")
    if not cfg.github_oauth_client_id or not cfg.github_oauth_client_secret:
        raise HTTPException(400, "github oauth not configured")
    redirect = f"{cfg.oauth_redirect_base}/auth/github/callback"
    try:
        info = await oauth.github_login_exchange(
            cfg.github_oauth_client_id, cfg.github_oauth_client_secret, code, redirect
        )
        if not info.get("email"):
            return RedirectResponse(f"{cfg.web_origin}/login?error=github_no_email")
        user = await svc.upsert_github_user(info["email"], info["name"], info["avatar"])
    except Exception as e:  # noqa: BLE001
        return RedirectResponse(f"{cfg.web_origin}/login?error={type(e).__name__}")
    return RedirectResponse(f"{cfg.web_origin}/auth/callback?token={_token(cfg, user)}")


# -- projects --------------------------------------------------------------
@app.post("/projects", response_model=ProjectOut)
async def create_project(body: ProjectCreate, svc: SvcDep, user: UserDep) -> ProjectOut:
    return _project_out(await svc.create_project(user.id, body.name))


@app.get("/projects", response_model=list[ProjectOut])
async def list_projects(svc: SvcDep, user: UserDep) -> list[ProjectOut]:
    return [_project_out(p) for p in await svc.list_projects(user.id)]


@app.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, svc: SvcDep, user: UserDep) -> ProjectOut:
    return _project_out(await _owned_project(svc, user, project_id))


@app.patch("/projects/{project_id}", response_model=ProjectOut)
async def rename_project(
    project_id: str, body: ProjectRename, svc: SvcDep, user: UserDep
) -> ProjectOut:
    await _owned_project(svc, user, project_id)
    proj = await svc.rename_project(project_id, body.name)
    assert proj is not None
    return _project_out(proj)


@app.get("/projects/{project_id}/analytics", response_model=AnalyticsOut)
async def project_analytics(project_id: str, svc: SvcDep, user: UserDep) -> dict:
    await _owned_project(svc, user, project_id)
    return await svc.project_analytics(project_id)


@app.get("/projects/{project_id}/mcp", response_model=McpInfoOut)
async def project_mcp(project_id: str, svc: SvcDep, user: UserDep, cfg: CfgDep) -> McpInfoOut:
    """The MCP endpoint + a per-project bearer token scoping it to this project."""
    await _owned_project(svc, user, project_id)
    return McpInfoOut(
        endpoint=cfg.mcp_public_url,
        token=create_mcp_token(project_id, cfg.jwt_secret),
    )


@app.delete("/projects/{project_id}/integrations/{provider}")
async def disconnect_provider(project_id: str, provider: str, svc: SvcDep, user: UserDep) -> dict:
    if provider not in ("github", "slack"):
        raise HTTPException(400, "unknown provider")
    await _owned_project(svc, user, project_id)
    await svc.disconnect_provider(project_id, provider)
    return {"disconnected": provider}


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, svc: SvcDep, user: UserDep) -> dict:
    await _owned_project(svc, user, project_id)
    await svc.delete_project(project_id)
    return {"deleted": project_id}


# -- integration OAuth (GitHub/Slack) — browser redirects, state/uuid-protected
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
    except Exception as e:  # noqa: BLE001
        return RedirectResponse(f"{cfg.web_origin}/projects/{project_id}?error={type(e).__name__}")
    return RedirectResponse(f"{cfg.web_origin}/projects/{project_id}?connected={provider}")


@app.get("/oauth/github/repos", response_model=list[RepoOut])
async def github_repos(
    svc: SvcDep, user: UserDep, project_id: Annotated[str, Query()]
) -> list[dict]:
    p = await _owned_project(svc, user, project_id)
    if not p.github_token:
        raise HTTPException(400, "GitHub not connected for this project")
    return await oauth.github_list_repos(p.github_token)


@app.get("/oauth/slack/channels", response_model=list[ChannelOut])
async def slack_channels(
    svc: SvcDep, user: UserDep, project_id: Annotated[str, Query()]
) -> list[dict]:
    p = await _owned_project(svc, user, project_id)
    if not p.slack_token:
        raise HTTPException(400, "Slack not connected for this project")
    return await oauth.slack_list_channels(p.slack_token)


# -- sources ---------------------------------------------------------------
@app.post("/sources", response_model=SourceOut)
async def create_source(body: SourceCreate, svc: SvcDep, user: UserDep) -> SourceOut:
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(400, f"unsupported kind {body.kind!r}")
    await _owned_project(svc, user, body.project_id)
    src = await svc.create_source(body.project_id, body.kind, body.config, body.secret)
    return _source_out(src)


@app.get("/sources", response_model=list[SourceOut])
async def list_sources(
    svc: SvcDep, user: UserDep, project_id: Annotated[str, Query()]
) -> list[SourceOut]:
    await _owned_project(svc, user, project_id)
    counts = await svc.source_event_counts(project_id)
    return [_source_out(s, counts.get(s.id, 0)) for s in await svc.list_sources(project_id)]


@app.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(source_id: str, svc: SvcDep, user: UserDep) -> SourceOut:
    return _source_out(await _owned_source(svc, user, source_id))


@app.delete("/sources/{source_id}")
async def delete_source(source_id: str, svc: SvcDep, user: UserDep) -> dict:
    await _owned_source(svc, user, source_id)
    await svc.delete_source(source_id)
    return {"deleted": source_id}


@app.post("/sources/{source_id}/sync", response_model=SyncOut)
async def sync_source(source_id: str, svc: SvcDep, user: UserDep) -> SyncOut:
    await _owned_source(svc, user, source_id)
    try:
        n = await svc.sync(source_id)
    except Exception as e:
        raise HTTPException(502, f"sync failed: {e}") from e
    return SyncOut(source_id=source_id, ingested=n)


@app.get("/events", response_model=list[EventOut])
async def list_events(
    svc: SvcDep,
    user: UserDep,
    project_id: Annotated[str, Query()],
    limit: Annotated[int, Query(le=500)] = 50,
) -> list[IngestedEvent]:
    await _owned_project(svc, user, project_id)
    return await svc.list_events(project_id, limit)


@app.get("/builds", response_model=list[BuildOut])
async def list_builds(
    svc: SvcDep,
    user: UserDep,
    project_id: Annotated[str, Query()],
    limit: Annotated[int, Query(le=500)] = 50,
) -> list[BuildLedger]:
    await _owned_project(svc, user, project_id)
    return await svc.list_builds(project_id, limit)


def run() -> None:
    import uvicorn

    s = IngestSettings()
    uvicorn.run("meaninggrid_ingest.main:app", host=s.api_host, port=s.api_port, reload=False)


if __name__ == "__main__":
    run()
