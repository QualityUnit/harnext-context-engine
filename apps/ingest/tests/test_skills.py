"""Skills CRUD over the ingest API: validation, content encodings, ownership,
and the project-delete cascade."""

import base64

import httpx
from harnext_ingest.main import app
from harnext_ingest.main import current_user as user_dep
from harnext_ingest.main import service as service_dep
from harnext_ingest.service import SourceService
from harnext_ingest.settings import IngestSettings
from harnext_shared import SkillFile, init_db, make_engine, make_sessionmaker, skill_file_meta
from sqlalchemy import func, inspect, select

SKILL_MD = """---
name: deploy-helper
description: Safely roll out the app
---

# Deploy Helper

Step-by-step deploy instructions.
"""

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00\xffnot-utf8"


class FakeProducer:
    async def send_event(self, topic, event):
        pass


async def _setup(tmp_path):
    """Service + app overrides with a switchable current user (for ownership
    tests). Returns (svc, engine, user, project, current-user holder)."""
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    svc = SourceService(make_sessionmaker(engine), FakeProducer(), IngestSettings())
    u = await svc.register("a@b.com", "hunter2", "A")
    p = await svc.create_project(u.id, "P")
    current = {"user": u}
    app.dependency_overrides[service_dep] = lambda: svc
    app.dependency_overrides[user_dep] = lambda: current["user"]
    return svc, engine, u, p, current


async def _teardown(engine):
    app.dependency_overrides.clear()
    await engine.dispose()


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _skill_body(project_id, name="deploy-helper", description=None, files=None):
    body = {
        "project_id": project_id,
        "name": name,
        "files": files if files is not None else [{"path": "SKILL.md", "content": SKILL_MD}],
    }
    if description is not None:
        body["description"] = description
    return body


async def test_create_skill_extracts_description(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            files = [
                {"path": "SKILL.md", "content": SKILL_MD},
                {"path": "scripts/run.py", "content": "print('hi')\n"},
            ]
            r = await c.post("/skills", json=_skill_body(p.id, files=files))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["project_id"] == p.id and body["name"] == "deploy-helper"
            # description pulled from the SKILL.md frontmatter
            assert body["description"] == "Safely roll out the app"
            # server-computed metadata matches the shared single source of truth
            by_path = {f["path"]: f for f in body["files"]}
            mime, size, digest = skill_file_meta("SKILL.md", SKILL_MD.encode())
            assert by_path["SKILL.md"]["mime_type"] == mime == "text/markdown"
            assert by_path["SKILL.md"]["size"] == size
            assert by_path["SKILL.md"]["hash"] == digest
            assert by_path["scripts/run.py"]["mime_type"] == "text/x-python"
            # create/update responses carry metadata only, never content
            assert "content" not in by_path["SKILL.md"]

            # an explicit description wins over the frontmatter
            r = await c.post(
                "/skills", json=_skill_body(p.id, name="other", description="Custom words")
            )
            assert r.status_code == 200
            assert r.json()["description"] == "Custom words"
    finally:
        await _teardown(engine)


async def test_list_skills_excludes_content(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            r = await c.post("/skills", json=_skill_body(p.id))
            assert r.status_code == 200
            r = await c.get("/skills", params={"project_id": p.id})
            assert r.status_code == 200
            skills = r.json()
            assert [s["name"] for s in skills] == ["deploy-helper"]
            for f in skills[0]["files"]:
                assert set(f) == {"path", "size", "hash", "mime_type"}  # no content/encoding
    finally:
        await _teardown(engine)


async def test_list_skills_never_loads_content_blobs(tmp_path):
    """The list path is metadata-only all the way down — the LargeBinary column
    must not even be read from the DB (one big support file per skill would
    otherwise be buffered on every dashboard refresh)."""
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        await svc.create_skill(
            p.id, "bulky", None, {"SKILL.md": SKILL_MD.encode(), "big.bin": b"\x00" * 4096}
        )
        for _skill, rows in await svc.list_skills(p.id):
            assert rows  # sanity: the files are listed
            for row in rows:
                assert "content" in inspect(row).unloaded
    finally:
        await _teardown(engine)


async def test_get_skill_content_encodings(tmp_path):
    """GET detail returns text/* + application/json files as utf-8 and
    everything else (here a PNG) as base64."""
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            files = [
                {"path": "SKILL.md", "content": SKILL_MD},
                {"path": "data.json", "content": '{"a": 1}'},
                {
                    "path": "assets/logo.png",
                    "content": base64.b64encode(PNG).decode(),
                    "encoding": "base64",
                },
            ]
            r = await c.post("/skills", json=_skill_body(p.id, files=files))
            assert r.status_code == 200
            skill_id = r.json()["id"]

            r = await c.get(f"/skills/{skill_id}")
            assert r.status_code == 200
            by_path = {f["path"]: f for f in r.json()["files"]}
            assert by_path["SKILL.md"]["encoding"] == "utf-8"
            assert by_path["SKILL.md"]["content"] == SKILL_MD
            assert by_path["data.json"]["encoding"] == "utf-8"
            assert by_path["data.json"]["content"] == '{"a": 1}'
            assert by_path["assets/logo.png"]["encoding"] == "base64"
            assert base64.b64decode(by_path["assets/logo.png"]["content"]) == PNG
            assert by_path["assets/logo.png"]["mime_type"] == "image/png"
    finally:
        await _teardown(engine)


async def test_update_skill_replaces_files(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            files = [
                {"path": "SKILL.md", "content": SKILL_MD},
                {"path": "old.txt", "content": "stale"},
            ]
            r = await c.post("/skills", json=_skill_body(p.id, files=files))
            skill_id = r.json()["id"]

            new_md = "---\ndescription: Rewritten skill\n---\n\nBody.\n"
            r = await c.put(
                f"/skills/{skill_id}",
                json={
                    "files": [
                        {"path": "SKILL.md", "content": new_md},
                        {"path": "scripts/new.py", "content": "pass\n"},
                    ]
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert [f["path"] for f in body["files"]] == ["SKILL.md", "scripts/new.py"]
            assert body["description"] == "Rewritten skill"  # re-extracted from the new SKILL.md

            # description-only update leaves the file set alone
            r = await c.put(f"/skills/{skill_id}", json={"description": "Manual override"})
            assert r.status_code == 200
            assert r.json()["description"] == "Manual override"
            assert [f["path"] for f in r.json()["files"]] == ["SKILL.md", "scripts/new.py"]

            # a replacement file set must still include SKILL.md
            r = await c.put(
                f"/skills/{skill_id}",
                json={"files": [{"path": "notes.md", "content": "x"}]},
            )
            assert r.status_code == 400
    finally:
        await _teardown(engine)


async def test_delete_skill(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            r = await c.post("/skills", json=_skill_body(p.id))
            skill_id = r.json()["id"]
            r = await c.delete(f"/skills/{skill_id}")
            assert r.status_code == 200 and r.json() == {"deleted": skill_id}
            assert (await c.get(f"/skills/{skill_id}")).status_code == 404
            assert (await c.get("/skills", params={"project_id": p.id})).json() == []
            # its files are gone from the DB too
            async with svc.sm() as s:
                assert await s.scalar(select(func.count()).select_from(SkillFile)) == 0
    finally:
        await _teardown(engine)


async def test_skill_ownership_rejected(tmp_path):
    """A user must not see or touch skills under another user's project."""
    svc, engine, u, p, current = await _setup(tmp_path)
    try:
        async with _client() as c:
            r = await c.post("/skills", json=_skill_body(p.id))
            skill_id = r.json()["id"]

            intruder = await svc.register("evil@b.com", "hunter2", "E")
            current["user"] = intruder
            assert (await c.post("/skills", json=_skill_body(p.id, name="x"))).status_code == 403
            assert (await c.get("/skills", params={"project_id": p.id})).status_code == 403
            assert (await c.get(f"/skills/{skill_id}")).status_code == 403
            r = await c.put(f"/skills/{skill_id}", json={"description": "hijack"})
            assert r.status_code == 403
            assert (await c.delete(f"/skills/{skill_id}")).status_code == 403

            current["user"] = u  # the owner still sees an untouched skill
            r = await c.get(f"/skills/{skill_id}")
            assert r.status_code == 200
            assert r.json()["description"] == "Safely roll out the app"
    finally:
        await _teardown(engine)


async def test_invalid_skill_name(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            for bad in ("Bad Name", "-leading-dash", "UPPER", "a" * 65, "dots.not.ok"):
                r = await c.post("/skills", json=_skill_body(p.id, name=bad))
                assert r.status_code == 400, bad
    finally:
        await _teardown(engine)


async def test_invalid_skill_file_paths(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            md = {"path": "SKILL.md", "content": SKILL_MD}
            for bad in (
                "../evil.md",
                "a/../../b.md",
                "/abs.md",
                "a\\b.md",
                "_manifest",
                "",
                "sub/_manifest",  # the manifest name is reserved at any depth
                "docs/SKILL.md",  # nested SKILL.md = a phantom skill to skill:// clients
                "a#b.txt",  # '#', '?' and '%' can't round-trip through a skill:// URI
                "a?b.txt",
                "a%20b.txt",
            ):
                files = [md, {"path": bad, "content": "x"}]
                r = await c.post("/skills", json=_skill_body(p.id, files=files))
                assert r.status_code == 400, bad
            # duplicate paths in one request
            r = await c.post("/skills", json=_skill_body(p.id, files=[md, dict(md)]))
            assert r.status_code == 400
            # undecodable base64 content
            files = [md, {"path": "bin", "content": "not base64!!", "encoding": "base64"}]
            r = await c.post("/skills", json=_skill_body(p.id, files=files))
            assert r.status_code == 400
    finally:
        await _teardown(engine)


async def test_file_dir_path_collision_rejected(tmp_path):
    """One file's path must not be another file's directory — such a set can
    never land on a real filesystem (materialize_skills, download_skill)."""
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            md = {"path": "SKILL.md", "content": SKILL_MD}
            for files in (
                [md, {"path": "SKILL.md/extra.txt", "content": "x"}],
                [md, {"path": "a", "content": "x"}, {"path": "a/b.txt", "content": "y"}],
                [md, {"path": "a/b.txt", "content": "y"}, {"path": "a", "content": "x"}],
            ):
                r = await c.post("/skills", json=_skill_body(p.id, files=files))
                assert r.status_code == 400, files
                assert "directory" in r.json()["detail"]
            # the same names at sibling depths are fine
            files = [md, {"path": "a/b.txt", "content": "x"}, {"path": "a/c/b.txt", "content": "y"}]
            assert (await c.post("/skills", json=_skill_body(p.id, files=files))).status_code == 200
    finally:
        await _teardown(engine)


async def test_missing_skill_md_rejected(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            files = [{"path": "notes.md", "content": "no entry file"}]
            r = await c.post("/skills", json=_skill_body(p.id, files=files))
            assert r.status_code == 400
            assert "SKILL.md" in r.json()["detail"]
    finally:
        await _teardown(engine)


async def test_duplicate_skill_name_conflict(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        async with _client() as c:
            assert (await c.post("/skills", json=_skill_body(p.id))).status_code == 200
            assert (await c.post("/skills", json=_skill_body(p.id))).status_code == 409
            # the same name under a different project is fine
            p2 = await svc.create_project(u.id, "P2")
            assert (await c.post("/skills", json=_skill_body(p2.id))).status_code == 200
    finally:
        await _teardown(engine)


async def test_project_delete_cascades_skills(tmp_path):
    svc, engine, u, p, _ = await _setup(tmp_path)
    try:
        other = await svc.create_project(u.id, "Other")
        skill, _files = await svc.create_skill(
            p.id, "doomed", None, {"SKILL.md": SKILL_MD.encode(), "extra.txt": b"x"}
        )
        survivor, _files = await svc.create_skill(
            other.id, "survivor", None, {"SKILL.md": SKILL_MD.encode()}
        )

        assert await svc.delete_project(p.id) is True
        assert await svc.get_skill(skill.id) is None
        assert await svc.list_skills(p.id) == []
        # the doomed skill's files are gone; the other project's skill survives
        async with svc.sm() as s:
            assert await s.scalar(select(func.count()).select_from(SkillFile)) == 1
        found = await svc.get_skill(survivor.id)
        assert found is not None and found[0].name == "survivor"
    finally:
        await _teardown(engine)
