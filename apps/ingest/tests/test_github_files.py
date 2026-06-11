"""Changed-file enrichment: fetch commit/PR files, apply caps, fail soft."""

import httpx
from harnext_ingest.connectors import github
from harnext_ingest.connectors.github import enrich_files
from harnext_ingest.service import SourceService
from harnext_ingest.settings import IngestSettings
from harnext_shared import init_db, make_engine, make_sessionmaker


class _FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):
        self.sent.append((topic, event))


class FakeResp:
    def __init__(self, status=200, json_body=None, content=b""):
        self.status_code = status
        self._json = json_body
        self.content = content

    def json(self):
        return self._json


class FakeClient:
    """Routes GitHub API calls to canned responses by URL shape."""

    def __init__(self, *, commit=None, pr_files=None, raw=None, fail=False):
        self.commit = commit
        self.pr_files = pr_files
        self.raw = raw or {}  # path-substring -> bytes
        self.fail = fail
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append(url)
        if self.fail:
            raise httpx.ConnectError("boom")
        if "/contents/" in url:
            for key, body in self.raw.items():
                if key in url:
                    return FakeResp(content=body)
            return FakeResp(status=404)
        if url.endswith("/files"):
            return FakeResp(json_body=self.pr_files)
        if "/commits/" in url:
            return FakeResp(json_body=self.commit)
        return FakeResp(status=404)


async def test_commit_files_fetches_content():
    client = FakeClient(
        commit={"files": [
            {"filename": "src/app.py", "status": "modified"},
            {"filename": "gone.txt", "status": "removed"},
        ]},
        raw={"src/app.py": b"print('hi')\n"},
    )
    data = {"sha": "abc"}
    await enrich_files(client, "acme/web", "com.github.commit", data)

    files = {f["path"]: f for f in data["files"]}
    assert files["src/app.py"]["content"] == "print('hi')\n"
    assert files["src/app.py"]["truncated"] is False
    # removed file is listed without content
    assert "content" not in files["gone.txt"] and files["gone.txt"]["status"] == "removed"


async def test_pr_files_fetches_content():
    client = FakeClient(
        pr_files=[{"filename": "a.py", "status": "added",
                   "contents_url": "https://api.github.com/repos/acme/web/contents/a.py?ref=h"}],
        raw={"/contents/a.py": b"x = 1\n"},
    )
    data = {"number": 9}
    await enrich_files(client, "acme/web", "com.github.pull_request", data)
    assert data["files"][0]["content"] == "x = 1\n"


async def test_per_file_byte_cap_truncates(monkeypatch):
    monkeypatch.setattr(github, "_MAX_FILE_BYTES", 8)
    client = FakeClient(
        commit={"files": [{"filename": "big.py", "status": "added"}]},
        raw={"big.py": b"0123456789ABCDEF"},
    )
    data = {"sha": "abc"}
    await enrich_files(client, "acme/web", "com.github.commit", data)
    f = data["files"][0]
    assert f["truncated"] is True and len(f["content"].encode()) <= 8


async def test_total_budget_caps_file_count(monkeypatch):
    monkeypatch.setattr(github, "_MAX_TOTAL_BYTES", 5)
    client = FakeClient(
        commit={"files": [
            {"filename": "a.py", "status": "added"},
            {"filename": "b.py", "status": "added"},
        ]},
        raw={"a.py": b"hello", "b.py": b"world"},
    )
    data = {"sha": "abc"}
    await enrich_files(client, "acme/web", "com.github.commit", data)
    with_content = [f for f in data["files"] if "content" in f]
    assert len(with_content) == 1  # second file overflows the total budget


async def test_binary_content_is_skipped():
    client = FakeClient(
        commit={"files": [{"filename": "logo.png", "status": "added"}]},
        raw={"logo.png": b"\xff\xfe\x00\x01"},  # invalid utf-8
    )
    data = {"sha": "abc"}
    await enrich_files(client, "acme/web", "com.github.commit", data)
    assert "content" not in data["files"][0]


async def test_enrich_is_fail_soft():
    client = FakeClient(fail=True)
    data = {"sha": "abc"}
    await enrich_files(client, "acme/web", "com.github.commit", data)  # must not raise
    assert "files" not in data


async def test_non_commit_pr_events_are_ignored():
    client = FakeClient()
    data = {"body": "hi"}
    await enrich_files(client, "acme/web", "com.github.issue", data)
    assert "files" not in data and client.calls == []


async def test_webhook_event_carries_files_into_produced_event(tmp_path, monkeypatch):
    """The full webhook path: ingest_github_event enriches each item, and the
    changed files ride along on the CloudEvent the classifier will consume."""

    async def fake_enrich(client, repo, ev_type, data):
        if ev_type == "com.github.commit":
            data["files"] = [{"path": "src/app.py", "status": "modified", "content": "x\n"}]

    monkeypatch.setattr("harnext_ingest.connectors.github.enrich_files", fake_enrich)

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    producer = _FakeProducer()
    svc = SourceService(make_sessionmaker(engine), producer, IngestSettings())
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.create_source(p.id, "github", {"repo": "acme/web"}, None)

        push = {
            "ref": "refs/heads/main",
            "repository": {"full_name": "acme/web", "default_branch": "main"},
            "commits": [{"id": "abc", "message": "fix", "timestamp": "2026-06-08T00:00:00Z",
                         "url": "u", "author": {"name": "ada"}}],
        }
        assert await svc.ingest_github_event("push", push) == 1
        ev = producer.sent[-1][1]
        assert ev.type == "com.github.commit"
        assert ev.data["files"][0]["path"] == "src/app.py"
        assert ev.data["files"][0]["content"] == "x\n"
    finally:
        await engine.dispose()
