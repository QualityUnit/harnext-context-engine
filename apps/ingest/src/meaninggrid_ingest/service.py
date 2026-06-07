"""Control-plane + sync service: users, projects, sources, and the sync that
pulls a source's activity into the raw Kafka topic."""

from __future__ import annotations

import json
import uuid
from typing import Protocol

from meaninggrid_shared import (
    RAW_EVENTS_TOPIC,
    BuildLedger,
    CloudEvent,
    IngestedEvent,
    Project,
    Source,
    User,
    utcnow,
)
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meaninggrid_ingest.connectors import get_connector
from meaninggrid_ingest.security import hash_password, verify_password
from meaninggrid_ingest.settings import IngestSettings


class ProducerLike(Protocol):
    async def send_event(self, topic: str, event: CloudEvent) -> None: ...


class SourceService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: ProducerLike,
        settings: IngestSettings,
    ) -> None:
        self.sm = sessionmaker
        self.producer = producer
        self.s = settings

    # -- auth ---------------------------------------------------------------
    async def get_user(self, user_id: str) -> User | None:
        async with self.sm() as s:
            return await s.get(User, user_id)

    async def _user_by_email(self, email: str) -> User | None:
        async with self.sm() as s:
            return (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()

    async def register(self, email: str, password: str, name: str | None) -> User:
        if await self._user_by_email(email) is not None:
            raise ValueError("email already registered")
        user = User(
            id=uuid.uuid4().hex,
            username=email,  # legacy column; keep populated + unique
            email=email,
            name=name or email.split("@")[0],
            password_hash=hash_password(password),
        )
        async with self.sm() as s:
            s.add(user)
            await s.commit()
            await s.refresh(user)
        return user

    async def authenticate(self, email: str, password: str) -> User | None:
        user = await self._user_by_email(email)
        if (
            user is None
            or not user.password_hash
            or not verify_password(password, user.password_hash)
        ):
            return None
        return user

    async def upsert_google_user(
        self, sub: str, email: str | None, name: str | None, picture: str | None
    ) -> User:
        """Find by google_sub, else link an existing email account, else create."""
        async with self.sm() as s:
            user = (
                await s.execute(select(User).where(User.google_sub == sub))
            ).scalar_one_or_none()
            if user is None and email:
                user = (
                    await s.execute(select(User).where(User.email == email))
                ).scalar_one_or_none()
            if user is None:
                user = User(
                    id=uuid.uuid4().hex,
                    username=email or sub,
                    email=email,
                    name=name or (email.split("@")[0] if email else "user"),
                    google_sub=sub,
                    avatar_url=picture,
                )
                s.add(user)
            else:
                user.google_sub = sub
                if picture:
                    user.avatar_url = picture
                if name and not user.name:
                    user.name = name
                if email and not user.email:
                    user.email = email
            await s.commit()
            await s.refresh(user)
            return user

    # -- projects ----------------------------------------------------------
    async def create_project(self, owner_id: str, name: str) -> Project:
        proj = Project(id=uuid.uuid4().hex, name=name, owner_id=owner_id)
        async with self.sm() as s:
            s.add(proj)
            await s.commit()
            await s.refresh(proj)
        return proj

    async def list_projects(self, owner_id: str) -> list[Project]:
        async with self.sm() as s:
            q = select(Project).where(Project.owner_id == owner_id).order_by(Project.created_at)
            return list((await s.execute(q)).scalars())

    async def get_project(self, project_id: str) -> Project | None:
        async with self.sm() as s:
            return await s.get(Project, project_id)

    async def delete_project(self, project_id: str) -> bool:
        async with self.sm() as s:
            proj = await s.get(Project, project_id)
            if proj is None:
                return False
            await s.delete(proj)
            await s.commit()
            return True

    async def set_github_token(self, project_id: str, login: str | None, token: str) -> None:
        async with self.sm() as s:
            proj = await s.get(Project, project_id)
            if proj:
                proj.github_login = login
                proj.github_token = token
                await s.commit()

    async def set_slack_token(
        self, project_id: str, team_id: str | None, team_name: str | None, token: str
    ) -> None:
        async with self.sm() as s:
            proj = await s.get(Project, project_id)
            if proj:
                proj.slack_team_id = team_id
                proj.slack_team_name = team_name
                proj.slack_token = token
                await s.commit()

    # -- sources -----------------------------------------------------------
    async def create_source(
        self, project_id: str, kind: str, config: dict, secret: str | None = None
    ) -> Source:
        proj = await self.get_project(project_id)
        if proj is None:
            raise KeyError(project_id)
        if secret is None:  # reuse the project's OAuth token
            secret = (
                proj.github_token
                if kind == "github"
                else proj.slack_token
                if kind == "slack"
                else None
            )
        src = Source(
            id=uuid.uuid4().hex,
            org_id=project_id,
            kind=kind,
            config_json=json.dumps(config),
            secret=secret,
            status="active",
        )
        async with self.sm() as s:
            s.add(src)
            await s.commit()
            await s.refresh(src)
        return src

    async def list_sources(self, project_id: str | None) -> list[Source]:
        async with self.sm() as s:
            q = select(Source).order_by(Source.created_at)
            if project_id:
                q = q.where(Source.org_id == project_id)
            return list((await s.execute(q)).scalars())

    async def get_source(self, source_id: str) -> Source | None:
        async with self.sm() as s:
            return await s.get(Source, source_id)

    async def delete_source(self, source_id: str) -> bool:
        async with self.sm() as s:
            src = await s.get(Source, source_id)
            if src is None:
                return False
            await s.delete(src)
            await s.commit()
            return True

    async def sync(self, source_id: str) -> int:
        src = await self.get_source(source_id)
        if src is None:
            raise KeyError(source_id)

        connector = get_connector(src.kind, github_per_page=self.s.github_per_page)
        try:
            result = await connector.fetch(
                org_id=src.org_id,
                config=json.loads(src.config_json),
                secret=src.secret,
                since=src.cursor,
            )
            for ev in result.events:
                await self.producer.send_event(RAW_EVENTS_TOPIC, ev)
                await self._record_ingested(src, ev)
            await self._mark_synced(source_id, result.cursor)
            return len(result.events)
        except Exception as e:
            await self._mark_error(source_id, str(e))
            raise

    async def _record_ingested(self, src: Source, ev: CloudEvent) -> None:
        async with self.sm() as s:
            await s.merge(
                IngestedEvent(
                    org_id=src.org_id,
                    event_id=ev.id,
                    source_id=src.id,
                    source=ev.source,
                    type=ev.type,
                    subject=ev.subject,
                    event_time=ev.time,
                    ingest_time=utcnow(),
                )
            )
            await s.commit()

    async def _mark_synced(self, source_id: str, cursor: str | None) -> None:
        async with self.sm() as s:
            src = await s.get(Source, source_id)
            if src:
                src.cursor = cursor
                src.last_sync_at = utcnow()
                src.status = "active"
                src.last_error = None
                await s.commit()

    async def _mark_error(self, source_id: str, error: str) -> None:
        async with self.sm() as s:
            src = await s.get(Source, source_id)
            if src:
                src.status = "error"
                src.last_error = error[:2000]
                await s.commit()

    async def list_events(self, project_id: str, limit: int = 50) -> list[IngestedEvent]:
        async with self.sm() as s:
            q = (
                select(IngestedEvent)
                .where(IngestedEvent.org_id == project_id)
                .order_by(desc(IngestedEvent.ingest_time))
                .limit(limit)
            )
            return list((await s.execute(q)).scalars())

    async def list_builds(self, project_id: str, limit: int = 50) -> list[BuildLedger]:
        async with self.sm() as s:
            q = (
                select(BuildLedger)
                .where(BuildLedger.org_id == project_id)
                .order_by(desc(BuildLedger.updated_at))
                .limit(limit)
            )
            return list((await s.execute(q)).scalars())
