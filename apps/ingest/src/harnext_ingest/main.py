"""Ingest API — auth (email/password + Google), projects, OAuth connect, sync."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from harnext_builder.agentfs.backend import get_backend
from harnext_builder.agentfs.store import OrgFsStore
from harnext_builder.settings import BuilderSettings
from harnext_shared import (
    AgentEvent,
    AgentSession,
    BuildLedger,
    IngestedEvent,
    McpRequest,
    Project,
    Skill,
    SkillFile,
    Source,
    User,
    create_mcp_token,
    decode_agent_access_token,
    init_db,
    make_engine,
    make_sessionmaker,
)
from harnext_shared.skills_fs import SKILL_NAME_RE

from harnext_ingest import mailchimp, oauth
from harnext_ingest.connectors import SUPPORTED_KINDS, event_connector, liveagent, stripe
from harnext_ingest.kafka import Producer
from harnext_ingest.schemas import (
    AgentEventBatchIn,
    AgentEventBatchOut,
    AgentEventOut,
    AgentSessionDetailOut,
    AgentSessionFinalizeIn,
    AgentSessionOpenIn,
    AgentSessionOut,
    AnalyticsOut,
    AuthOut,
    BetaSignupIn,
    BetaSignupOut,
    BuildOut,
    ChannelOut,
    DepartmentOut,
    DeviceApproveIn,
    DeviceCodeOut,
    DeviceDenyIn,
    DeviceLookupOut,
    EventOut,
    FsFileOut,
    FsListOut,
    FsWriteIn,
    FsWriteOut,
    LiveAgentConnectIn,
    LoginIn,
    McpInfoOut,
    McpRequestOut,
    McpStatsOut,
    ProjectCreate,
    ProjectOut,
    ProjectRename,
    RegisterIn,
    RepoOut,
    SkillCreate,
    SkillFileIn,
    SkillFileOut,
    SkillOut,
    SkillUpdate,
    SourceCreate,
    SourceOut,
    StripeConnectIn,
    SyncOut,
    TagOut,
    TokenOut,
    UserOut,
)
from harnext_ingest.security import create_token, decode_token
from harnext_ingest.service import SourceService
from harnext_ingest.settings import IngestSettings

log = logging.getLogger("ingest.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = IngestSettings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)
    producer = Producer(settings.kafka_bootstrap_servers)
    await producer.start()
    app.state.settings = settings
    app.state.service = SourceService(sm, producer, settings)
    # The org context filesystem the builder maintains — same store (backend +
    # snapshot metadata), so the dashboard browses/edits exactly what the agent
    # sees. AgentFS config is read from BuilderSettings (the shared .env).
    app.state.fs_store = OrgFsStore(get_backend(BuilderSettings()), sm)
    try:
        yield
    finally:
        await producer.stop()
        await engine.dispose()


_BOOT = IngestSettings()
app = FastAPI(title="Harnext Ingest", lifespan=lifespan)
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


def fs_store() -> OrgFsStore:
    return app.state.fs_store


SvcDep = Annotated[SourceService, Depends(service)]
CfgDep = Annotated[IngestSettings, Depends(settings)]
FsDep = Annotated[OrgFsStore, Depends(fs_store)]


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


@dataclass
class AgentPrincipal:
    """The tenant a harness access token is scoped to (parallel to ``current_user``)."""

    org_id: str
    user_id: str


async def current_agent(
    svc: SvcDep, cfg: CfgDep, authorization: Annotated[str | None, Header()] = None
) -> AgentPrincipal:
    """Resolve the project (org) a pushed-conversation request is scoped to from a
    harness access token. The granted org is carried in the JWT claim; we confirm
    the project still exists so a deleted project's token stops working."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    claims = decode_agent_access_token(authorization[7:], cfg.jwt_secret)
    if not claims:
        raise HTTPException(401, "invalid or expired token")
    if await svc.get_project(claims["org"]) is None:
        raise HTTPException(401, "project not found")
    return AgentPrincipal(org_id=claims["org"], user_id=claims["sub"])


AgentDep = Annotated[AgentPrincipal, Depends(current_agent)]


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
        discord_guild_name=p.discord_guild_name,
        discord_connected=bool(p.discord_guild_id),
        liveagent_base_url=p.liveagent_base_url,
        liveagent_connected=bool(p.liveagent_api_key),
        stripe_account_name=p.stripe_account_name,
        stripe_connected=bool(p.stripe_api_key),
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


def _maybe_json(raw: str | None) -> object:
    """Parse a stored JSON payload, falling back to the raw string if it was
    size-capped (and so no longer valid JSON) at write time."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def _mcp_request_out(r: McpRequest) -> McpRequestOut:
    return McpRequestOut(
        id=r.id,
        tool=r.tool,
        params=_maybe_json(r.params_json),
        status=r.status,
        response=_maybe_json(r.response_json),
        error=r.error,
        duration_ms=r.duration_ms,
        created_at=r.created_at,
    )


def _agent_session_out(s: AgentSession) -> AgentSessionOut:
    return AgentSessionOut(
        id=s.id,
        org_id=s.org_id,
        client_session_id=s.client_session_id,
        harness=s.harness,
        model=s.model,
        cwd=s.cwd,
        title=s.title,
        status=s.status,
        stop_reason=s.stop_reason,
        usage=_maybe_json(s.usage_json),
        event_count=s.event_count,
        started_at=s.started_at,
        ended_at=s.ended_at,
    )


def _agent_event_out(e: AgentEvent) -> AgentEventOut:
    return AgentEventOut(
        seq=e.seq, type=e.type, payload=_maybe_json(e.payload_json), created_at=e.created_at
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


async def _owned_skill(
    svc: SourceService, user: User, skill_id: str
) -> tuple[Skill, list[SkillFile]]:
    found = await svc.get_skill(skill_id)
    if found is None:
        raise HTTPException(404, "skill not found")
    await _owned_project(svc, user, found[0].org_id)
    return found


def _safe_relpath(path: str) -> str:
    """Normalize a client-supplied FS path and reject anything that could escape
    the org's filesystem (absolute paths, ``..`` traversal)."""
    rel = path.strip().lstrip("/")
    pp = PurePosixPath(rel)
    if not rel or pp.is_absolute() or any(part == ".." for part in pp.parts):
        raise HTTPException(400, "invalid path")
    return str(pp)


def _safe_skill_path(path: str) -> str:
    """Normalize a skill file path: relative POSIX, no leading "/", no "..", no
    "\\\\". '#', '?' and '%' are rejected because they cannot round-trip through
    a ``skill://`` URI. "_manifest" basenames are reserved for the MCP manifest
    resource, and "SKILL.md" is only valid at the root — a nested SKILL.md is
    listed as a phantom skill by ``skill://`` clients (they match any URI ending
    in "/SKILL.md")."""
    rel = path.strip()
    pp = PurePosixPath(rel)
    if (
        not rel
        or rel.startswith("/")
        or "\\" in rel
        or any(c in rel for c in "#?%")
        or any(part == ".." for part in pp.parts)
        or str(pp) == "."
        or pp.name == "_manifest"
        or (pp.name == "SKILL.md" and len(pp.parts) > 1)
    ):
        raise HTTPException(400, f"invalid skill file path {path!r}")
    return str(pp)


def _decode_skill_files(files: list[SkillFileIn]) -> dict[str, bytes]:
    """Validate + decode a client-supplied skill file set to ``{path: bytes}``.
    Every skill must carry its ``SKILL.md`` entry file."""
    out: dict[str, bytes] = {}
    dirs: set[str] = set()  # every ancestor directory implied by a file path
    for f in files:
        rel = _safe_skill_path(f.path)
        if rel in out:
            raise HTTPException(400, f"duplicate skill file path {rel!r}")
        dirs.update(str(p) for p in PurePosixPath(rel).parents if str(p) != ".")
        if f.encoding == "base64":
            try:
                out[rel] = base64.b64decode(f.content, validate=True)
            except (binascii.Error, ValueError) as e:
                raise HTTPException(400, f"invalid base64 content for {rel!r}") from e
        else:
            out[rel] = f.content.encode("utf-8")
    for clash in sorted(set(out) & dirs):  # "a" + "a/b" can't both land on disk
        raise HTTPException(400, f"skill file path {clash!r} is also a directory of another file")
    if "SKILL.md" not in out:
        raise HTTPException(400, "a skill requires a SKILL.md file")
    return out


def _skill_file_out(f: SkillFile, include_content: bool) -> SkillFileOut:
    out = SkillFileOut(path=f.path, size=f.size, hash=f.hash, mime_type=f.mime_type)
    if include_content:
        is_text = f.mime_type.startswith("text/") or f.mime_type == "application/json"
        if is_text:
            try:
                out.content, out.encoding = f.content.decode("utf-8"), "utf-8"
                return out
            except UnicodeDecodeError:
                pass  # mislabeled binary — fall through to base64
        out.content, out.encoding = base64.b64encode(f.content).decode("ascii"), "base64"
    return out


def _skill_out(skill: Skill, files: list[SkillFile], include_content: bool = False) -> SkillOut:
    return SkillOut(
        id=skill.id,
        project_id=skill.org_id,
        name=skill.name,
        description=skill.description,
        files=[_skill_file_out(f, include_content) for f in files],
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


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
            "discord": bool(cfg.discord_oauth_client_id),
            "google": bool(cfg.google_oauth_client_id),
        },
        # The harness device-flow surface is always available (no external app to
        # register); a CLI can probe this to discover the client id to use.
        "agent_oauth": {"device_flow": True, "client_id": cfg.agent_oauth_client_id},
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


@app.post("/beta/signup", response_model=BetaSignupOut)
async def beta_signup(body: BetaSignupIn, cfg: CfgDep) -> BetaSignupOut:
    """Register interest in the closed beta — tag the contact in Mailchimp.

    Public (no auth): the "register" page calls this to collect a name + email
    while Harnext isn't generally available. The contact is upserted into the
    configured audience and tagged; we store nothing locally."""
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "a valid email is required")
    if not cfg.mailchimp_api_key:
        raise HTTPException(503, "beta registration is not configured on this instance")
    try:
        status = await mailchimp.upsert_member(
            api_key=cfg.mailchimp_api_key,
            audience_id=cfg.mailchimp_audience_id,
            email=email,
            name=body.name,
            tag=cfg.mailchimp_beta_tag,
        )
    except mailchimp.MailchimpError as e:
        raise HTTPException(502, f"could not register interest: {e}") from e
    return BetaSignupOut(ok=True, status=status)


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
    except Exception as e:  # noqa: BLE001
        return RedirectResponse(f"{cfg.web_origin}/login?error={type(e).__name__}")
    if not info.get("email"):
        return RedirectResponse(f"{cfg.web_origin}/login?error=github_no_email")

    # Closed-beta funnel: while the dashboard isn't public, a GitHub sign-in
    # registers interest rather than opening the app — tag the email in Mailchimp
    # and show the newsletter page. No account or session is created. A capture
    # failure must not block the user, so we still land them on the thank-you page.
    if cfg.github_beta_capture:
        if cfg.mailchimp_api_key:
            try:
                await mailchimp.upsert_member(
                    api_key=cfg.mailchimp_api_key,
                    audience_id=cfg.mailchimp_audience_id,
                    email=info["email"],
                    name=info.get("name"),
                    tag=cfg.mailchimp_beta_tag,
                )
            except mailchimp.MailchimpError as e:
                log.warning("github beta capture: mailchimp upsert failed (%s)", e)
        else:
            log.warning("github beta capture on but MAILCHIMP_API_KEY unset — lead not saved")
        return RedirectResponse(f"{cfg.web_origin}/register?joined=1")

    try:
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


@app.get("/projects/{project_id}/mcp-requests/stats", response_model=McpStatsOut)
async def project_mcp_stats(project_id: str, svc: SvcDep, user: UserDep) -> dict:
    """Aggregate MCP request volume (per-day series, totals, per-tool, errors)."""
    await _owned_project(svc, user, project_id)
    return await svc.mcp_analytics(project_id)


@app.get("/projects/{project_id}/mcp-requests", response_model=list[McpRequestOut])
async def project_mcp_requests(
    project_id: str,
    svc: SvcDep,
    user: UserDep,
    limit: Annotated[int, Query(le=500)] = 50,
) -> list[McpRequestOut]:
    """Recent MCP tool calls (request + response) for this project, newest first."""
    await _owned_project(svc, user, project_id)
    return [_mcp_request_out(r) for r in await svc.list_mcp_requests(project_id, limit)]


# -- context filesystem (the agent's working files) ------------------------
# Browse + edit the org's AgentFS context store — exactly what the builder
# agent reads/writes. Reads serve the LIVE working FS (what the next build will
# see); a write commits an ``edit`` snapshot so it's durable and becomes the
# consistent view the MCP read path mounts.
@app.get("/projects/{project_id}/fs", response_model=FsListOut)
async def list_fs(project_id: str, svc: SvcDep, user: UserDep, store: FsDep) -> FsListOut:
    await _owned_project(svc, user, project_id)
    await store.ensure(project_id)  # materialize the seed layout on first open
    files = await store.list_files(project_id)
    latest = await store.latest_snapshot(project_id)
    return FsListOut(files=sorted(files), snapshot_id=latest.id if latest else None)


@app.get("/projects/{project_id}/fs/file", response_model=FsFileOut)
async def read_fs_file(
    project_id: str, svc: SvcDep, user: UserDep, store: FsDep, path: Annotated[str, Query()]
) -> FsFileOut:
    await _owned_project(svc, user, project_id)
    rel = _safe_relpath(path)
    content = await store.read_file(project_id, rel)
    if content is None:
        raise HTTPException(404, "file not found")
    return FsFileOut(path=rel, content=content, size=len(content.encode("utf-8")))


@app.put("/projects/{project_id}/fs/file", response_model=FsWriteOut)
async def write_fs_file(
    project_id: str, body: FsWriteIn, svc: SvcDep, user: UserDep, store: FsDep
) -> FsWriteOut:
    await _owned_project(svc, user, project_id)
    rel = _safe_relpath(body.path)
    snapshot_id = await store.write_file(project_id, rel, body.content)
    return FsWriteOut(path=rel, size=len(body.content.encode("utf-8")), snapshot_id=snapshot_id)


@app.delete("/projects/{project_id}/integrations/{provider}")
async def disconnect_provider(project_id: str, provider: str, svc: SvcDep, user: UserDep) -> dict:
    if provider not in ("github", "slack", "discord", "liveagent", "stripe", "youtube"):
        raise HTTPException(400, "unknown provider")
    await _owned_project(svc, user, project_id)
    await svc.disconnect_provider(project_id, provider)
    return {"disconnected": provider}


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, svc: SvcDep, user: UserDep) -> dict:
    await _owned_project(svc, user, project_id)
    await svc.delete_project(project_id)
    return {"deleted": project_id}


# -- agent harness OAuth (RFC 8628 device flow) ----------------------------
# A CLI harness obtains an access+refresh token to push its conversation logs.
# The CLI is a public client; the security boundary is the human approval step
# in the dashboard. Token-endpoint responses use OAuth-standard error bodies +
# HTTP 400 so any stock OAuth client works.
_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def _oauth_error(error: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status)


@app.post("/oauth/device/code", response_model=DeviceCodeOut)
async def device_code(
    svc: SvcDep,
    cfg: CfgDep,
    client_id: Annotated[str, Form()],
) -> DeviceCodeOut | JSONResponse:
    if client_id != cfg.agent_oauth_client_id:
        return _oauth_error("invalid_client", 401)
    req = await svc.create_device_request(client_id)
    base = f"{cfg.web_origin}/device"
    return DeviceCodeOut(
        device_code=req.device_code,
        user_code=req.user_code,
        verification_uri=base,
        verification_uri_complete=f"{base}?code={req.user_code}",
        expires_in=cfg.device_code_ttl_seconds,
        interval=req.interval,
    )


@app.post("/oauth/token", response_model=TokenOut)
async def oauth_token(
    svc: SvcDep,
    cfg: CfgDep,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    device_code: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
) -> TokenOut | JSONResponse:
    if client_id != cfg.agent_oauth_client_id:
        return _oauth_error("invalid_client", 401)

    if grant_type == _DEVICE_GRANT:
        if not device_code:
            return _oauth_error("invalid_request")
        outcome, tokens = await svc.poll_device(device_code)
        if outcome != "approved" or tokens is None:
            return _oauth_error(outcome)  # authorization_pending / slow_down / …
        access, refresh = tokens
        return TokenOut(
            access_token=access,
            expires_in=cfg.agent_access_token_ttl_seconds,
            refresh_token=refresh,
        )

    if grant_type == "refresh_token":
        if not refresh_token:
            return _oauth_error("invalid_request")
        rotated = await svc.rotate_refresh(refresh_token, client_id)
        if rotated is None:
            return _oauth_error("invalid_grant")
        access, refresh = rotated
        return TokenOut(
            access_token=access,
            expires_in=cfg.agent_access_token_ttl_seconds,
            refresh_token=refresh,
        )

    return _oauth_error("unsupported_grant_type")


@app.get("/oauth/device/lookup", response_model=DeviceLookupOut)
async def device_lookup(
    user: UserDep, svc: SvcDep, user_code: Annotated[str, Query()]
) -> DeviceLookupOut:
    """Dashboard: resolve a user_code so the approve page can show the requesting
    client before the user picks a project."""
    req = await svc.get_device_by_user_code(user_code)
    if req is None:
        raise HTTPException(404, "unknown code")
    return DeviceLookupOut(
        user_code=req.user_code,
        client_id=req.client_id,
        status=req.status,
        expires_at=req.expires_at,
    )


@app.post("/oauth/device/approve")
async def device_approve(body: DeviceApproveIn, user: UserDep, svc: SvcDep) -> dict:
    """Dashboard: bind a pending device request to one of the user's projects."""
    await _owned_project(svc, user, body.project_id)
    outcome = await svc.approve_device(body.user_code, body.project_id, user.id)
    if outcome == "not_found":
        raise HTTPException(404, "unknown code")
    if outcome == "expired":
        raise HTTPException(410, "code expired")
    if outcome == "already":
        raise HTTPException(409, "code already resolved")
    return {"status": "approved"}


@app.post("/oauth/device/deny")
async def device_deny(body: DeviceDenyIn, user: UserDep, svc: SvcDep) -> dict:
    outcome = await svc.deny_device(body.user_code)
    if outcome == "not_found":
        raise HTTPException(404, "unknown code")
    return {"status": "denied"}


# -- pushed agent conversations (store-only) -------------------------------
# Authed by the harness access token (current_agent → the granted project).
async def _agent_owned_session(svc: SourceService, principal: AgentPrincipal, session_id: str):
    sess = await svc.get_agent_session(session_id)
    if sess is None or sess.org_id != principal.org_id:
        raise HTTPException(404, "session not found")
    return sess


@app.post("/agent/sessions", response_model=AgentSessionOut)
async def open_agent_session(
    body: AgentSessionOpenIn, svc: SvcDep, principal: AgentDep
) -> AgentSessionOut:
    sess = await svc.open_agent_session(
        principal.org_id, body.client_session_id, body.harness, body.model, body.cwd, body.title
    )
    return _agent_session_out(sess)


@app.post("/agent/sessions/{session_id}/events", response_model=AgentEventBatchOut)
async def append_agent_events(
    session_id: str, body: AgentEventBatchIn, svc: SvcDep, cfg: CfgDep, principal: AgentDep
) -> AgentEventBatchOut:
    sess = await _agent_owned_session(svc, principal, session_id)
    if sess.status == "closed":
        raise HTTPException(409, "session is finalized")
    if len(body.events) > cfg.agent_event_max_batch:
        raise HTTPException(413, f"batch too large (max {cfg.agent_event_max_batch})")
    result = await svc.append_agent_events(
        session_id, principal.org_id, [e.model_dump() for e in body.events]
    )
    return AgentEventBatchOut(session_id=session_id, **result)


@app.post("/agent/sessions/{session_id}/finalize", response_model=AgentSessionOut)
async def finalize_agent_session(
    session_id: str, body: AgentSessionFinalizeIn, svc: SvcDep, principal: AgentDep
) -> AgentSessionOut:
    await _agent_owned_session(svc, principal, session_id)
    sess = await svc.finalize_agent_session(session_id, body.stop_reason, body.usage)
    if sess is None:
        raise HTTPException(404, "session not found")
    return _agent_session_out(sess)


@app.get("/projects/{project_id}/agent-sessions", response_model=list[AgentSessionOut])
async def list_agent_sessions(
    project_id: str,
    svc: SvcDep,
    user: UserDep,
    limit: Annotated[int, Query(le=500)] = 50,
) -> list[AgentSessionOut]:
    """Dashboard: recent pushed conversations for this project, newest first."""
    await _owned_project(svc, user, project_id)
    return [_agent_session_out(s) for s in await svc.list_agent_sessions(project_id, limit)]


@app.get("/projects/{project_id}/agent-sessions/{session_id}", response_model=AgentSessionDetailOut)
async def get_agent_session(
    project_id: str, session_id: str, svc: SvcDep, user: UserDep
) -> AgentSessionDetailOut:
    """Dashboard: one conversation with its ordered turns."""
    await _owned_project(svc, user, project_id)
    sess = await svc.get_agent_session(session_id)
    if sess is None or sess.org_id != project_id:
        raise HTTPException(404, "session not found")
    events = await svc.get_agent_session_events(session_id)
    return AgentSessionDetailOut(
        session=_agent_session_out(sess), events=[_agent_event_out(e) for e in events]
    )


# -- integration OAuth (GitHub/Slack) — browser redirects, state/uuid-protected
def _creds(provider: str, cfg: IngestSettings) -> tuple[str | None, str | None]:
    if provider == "github":
        return cfg.github_oauth_client_id, cfg.github_oauth_client_secret
    if provider == "slack":
        return cfg.slack_oauth_client_id, cfg.slack_oauth_client_secret
    if provider == "discord":
        return cfg.discord_oauth_client_id, cfg.discord_oauth_client_secret
    return None, None


@app.get("/oauth/{provider}/start")
async def oauth_start(
    provider: str, svc: SvcDep, cfg: CfgDep, project_id: Annotated[str, Query()]
) -> RedirectResponse:
    if provider not in ("github", "slack", "discord"):
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
    authorize_url = {
        "github": oauth.github_authorize_url,
        "slack": oauth.slack_authorize_url,
        "discord": oauth.discord_authorize_url,
    }[provider]
    return RedirectResponse(authorize_url(client_id, redirect, state))


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
        elif provider == "slack":
            res = await oauth.slack_exchange(client_id, client_secret, code, redirect)
            await svc.set_slack_token(project_id, res["team_id"], res["team_name"], res["token"])
        else:  # discord — bot invite; record the guild (poller uses the app bot token)
            res = await oauth.discord_exchange(client_id, client_secret, code, redirect)
            await svc.set_discord_guild(project_id, res["guild_id"], res["guild_name"])
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


@app.get("/oauth/discord/channels", response_model=list[ChannelOut])
async def discord_channels(
    svc: SvcDep, user: UserDep, cfg: CfgDep, project_id: Annotated[str, Query()]
) -> list[dict]:
    p = await _owned_project(svc, user, project_id)
    if not p.discord_guild_id:
        raise HTTPException(400, "Discord not connected for this project")
    if not cfg.discord_bot_token:
        raise HTTPException(503, "discord bot token not configured")
    return await oauth.discord_list_channels(p.discord_guild_id, cfg.discord_bot_token)


# -- LiveAgent integration (no OAuth — a per-install base URL + v3 API key) --
@app.put("/projects/{project_id}/integrations/liveagent", response_model=ProjectOut)
async def connect_liveagent(
    project_id: str, body: LiveAgentConnectIn, svc: SvcDep, user: UserDep
) -> ProjectOut:
    """Validate a LiveAgent base URL + v3 API key (by listing departments) and
    store them on the project. Returns the updated project."""
    await _owned_project(svc, user, project_id)
    base = liveagent.normalize_base_url(body.base_url)
    if not body.api_key.strip():
        raise HTTPException(400, "an API key is required")
    try:
        await liveagent.verify_credentials(base, body.api_key)
    except Exception as e:  # noqa: BLE001 — surfaced to the user as a 400
        raise HTTPException(400, f"could not reach LiveAgent: {e}") from e
    await svc.set_liveagent_integration(project_id, base, body.api_key)
    proj = await svc.get_project(project_id)
    assert proj is not None
    return _project_out(proj)


# -- Stripe integration (no OAuth — a read-only Restricted API key) -----------
@app.put("/projects/{project_id}/integrations/stripe", response_model=ProjectOut)
async def connect_stripe(
    project_id: str, body: StripeConnectIn, svc: SvcDep, user: UserDep
) -> ProjectOut:
    """Validate a Stripe Restricted key (by reading the events list) and store it
    on the project along with the resolved account display name. Returns the
    updated project."""
    await _owned_project(svc, user, project_id)
    if not body.api_key.strip():
        raise HTTPException(400, "an API key is required")
    try:
        info = await stripe.verify_credentials(body.api_key.strip())
    except Exception as e:  # noqa: BLE001 — surfaced to the user as a 400
        raise HTTPException(400, f"could not reach Stripe: {e}") from e
    await svc.set_stripe_integration(project_id, info["name"], body.api_key.strip())
    proj = await svc.get_project(project_id)
    assert proj is not None
    return _project_out(proj)


async def _liveagent_creds(svc: SourceService, user: User, project_id: str) -> tuple[str, str]:
    p = await _owned_project(svc, user, project_id)
    if not (p.liveagent_base_url and p.liveagent_api_key):
        raise HTTPException(400, "LiveAgent not connected for this project")
    return p.liveagent_base_url, p.liveagent_api_key


@app.get("/liveagent/departments", response_model=list[DepartmentOut])
async def liveagent_departments(
    svc: SvcDep, user: UserDep, project_id: Annotated[str, Query()]
) -> list[dict]:
    base, key = await _liveagent_creds(svc, user, project_id)
    try:
        return await liveagent.list_departments(base, key)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LiveAgent error: {e}") from e


@app.get("/liveagent/tags", response_model=list[TagOut])
async def liveagent_tags(
    svc: SvcDep, user: UserDep, project_id: Annotated[str, Query()]
) -> list[dict]:
    base, key = await _liveagent_creds(svc, user, project_id)
    try:
        return await liveagent.list_tags(base, key)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LiveAgent error: {e}") from e


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


# -- skills ------------------------------------------------------------------
# Project-scoped skill directories shared by everyone in the project: a named
# set of files with a mandatory SKILL.md entry file. Served over MCP as
# skill://{name}/... and materialized into agent working dirs by the builder.
@app.post("/skills", response_model=SkillOut, response_model_exclude_none=True)
async def create_skill(body: SkillCreate, svc: SvcDep, user: UserDep) -> SkillOut:
    await _owned_project(svc, user, body.project_id)
    name = body.name.strip()
    if not SKILL_NAME_RE.match(name):
        raise HTTPException(400, f"invalid skill name {body.name!r} (want {SKILL_NAME_RE.pattern})")
    files = _decode_skill_files(body.files)
    try:
        skill, rows = await svc.create_skill(body.project_id, name, body.description, files)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return _skill_out(skill, rows)


@app.get("/skills", response_model=list[SkillOut], response_model_exclude_none=True)
async def list_skills(
    svc: SvcDep, user: UserDep, project_id: Annotated[str, Query()]
) -> list[SkillOut]:
    await _owned_project(svc, user, project_id)
    return [_skill_out(sk, rows) for sk, rows in await svc.list_skills(project_id)]


@app.get("/skills/{skill_id}", response_model=SkillOut)
async def get_skill(skill_id: str, svc: SvcDep, user: UserDep) -> SkillOut:
    skill, rows = await _owned_skill(svc, user, skill_id)
    return _skill_out(skill, rows, include_content=True)


@app.put("/skills/{skill_id}", response_model=SkillOut, response_model_exclude_none=True)
async def update_skill(skill_id: str, body: SkillUpdate, svc: SvcDep, user: UserDep) -> SkillOut:
    await _owned_skill(svc, user, skill_id)
    files = _decode_skill_files(body.files) if body.files is not None else None
    updated = await svc.update_skill(skill_id, body.description, files)
    assert updated is not None
    return _skill_out(*updated)


@app.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, svc: SvcDep, user: UserDep) -> dict:
    await _owned_skill(svc, user, skill_id)
    await svc.delete_skill(skill_id)
    return {"deleted": skill_id}


async def _handle_webhook(kind: str, secret: str, request: Request, ingest) -> dict:
    """Shared event-webhook flow: verify the signature, parse via the kind's
    EventConnector, return its handshake reply, else fan each parsed event out
    through ``ingest(*args)`` (the provider's service method). Signed but
    otherwise public — no bearer auth."""
    conn = event_connector(kind)
    assert conn is not None  # only kinds with a registered EventConnector reach here
    raw = await request.body()
    if not conn.verify(secret=secret, headers=request.headers, body=raw):
        raise HTTPException(401, f"bad {kind} signature")
    response, dispatches = conn.parse(headers=request.headers, body=raw)
    if response is not None:  # endpoint handshake (slack url_verification / github ping)
        return response
    for args in dispatches:
        await ingest(*args)
    return {"ok": True}


@app.post("/webhooks/slack")
async def slack_webhook(request: Request, svc: SvcDep, cfg: CfgDep) -> dict:
    """Slack Events API receiver (real-time) — pushes messages into the same
    pipeline the poller feeds."""
    if not cfg.slack_signing_secret:
        raise HTTPException(503, "slack webhook not configured")
    return await _handle_webhook("slack", cfg.slack_signing_secret, request, svc.ingest_slack_event)


@app.post("/webhooks/github")
async def github_webhook(request: Request, svc: SvcDep, cfg: CfgDep) -> dict:
    """GitHub repo webhook receiver (real-time) — pushes push/issues/PR/comment
    events into the same pipeline the poller feeds."""
    if not cfg.github_webhook_secret:
        raise HTTPException(503, "github webhook not configured")
    return await _handle_webhook(
        "github", cfg.github_webhook_secret, request, svc.ingest_github_event
    )


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
    uvicorn.run("harnext_ingest.main:app", host=s.api_host, port=s.api_port, reload=False)


if __name__ == "__main__":
    run()
