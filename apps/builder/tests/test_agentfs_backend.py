"""OrgFsStore + backend round-trip: ensure → build → snapshot → read → rollback.

Runs against the git backend always, and the agentfs backend when the binary is
available (so CI without agentfs still covers the contract).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from harnext_builder.agentfs.agentfs_backend import AgentFsBackend, resolve_agentfs_bin
from harnext_builder.agentfs.git_backend import GitBackend
from harnext_builder.agentfs.store import OrgFsStore
from harnext_shared import init_db, make_engine, make_sessionmaker


def _agentfs_available() -> bool:
    bin_ = resolve_agentfs_bin("agentfs")
    if not (shutil.which(bin_) or Path(bin_).exists()):
        return False
    try:
        subprocess.run([bin_, "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _make_backend(name: str, root: Path):
    if name == "git":
        return GitBackend(root)
    return AgentFsBackend(root)


# A portable "build" command: write a file into the FS working directory.
WRITE_NOTE = [sys.executable, "-c", "open('entities/note.md','w').write('hello world')"]


BACKENDS = ["git"]
if _agentfs_available():
    BACKENDS.append("agentfs")


@pytest.fixture
async def store(tmp_path, request):
    backend = _make_backend(request.param, tmp_path / "fs")
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    yield OrgFsStore(backend, make_sessionmaker(engine)), request.param
    await engine.dispose()


@pytest.mark.parametrize("store", BACKENDS, indirect=True)
async def test_full_roundtrip(store):
    fs, _backend_name = store
    org = "acme"

    # ensure: creates + seeds the FS and records a genesis snapshot
    await fs.ensure(org)
    genesis = await fs.latest_snapshot(org)
    assert genesis is not None and genesis.kind == "genesis"
    seeded = await fs.list_files(org)
    assert "CLAUDE.md" in seeded
    assert "_meta/schema.md" in seeded
    assert (await fs.read_file(org, "CLAUDE.md")).startswith("# Context Filesystem")

    # build: run a command that writes a new file into the FS
    result = await fs.run_build(org, WRITE_NOTE, env={}, timeout_s=60)
    assert result.ok, result.stderr

    # commit a new snapshot; latest advances; the new file is readable from it
    new_id = await fs.commit_snapshot(org, build_id="b1", parent_snapshot_id=genesis.id)
    latest = await fs.latest_snapshot(org)
    assert latest is not None and latest.id == new_id and latest.kind == "build"
    assert await fs.read_file(org, "entities/note.md") == "hello world"

    # rollback to genesis: the note is gone from the live FS
    await fs.rollback(org, genesis)
    assert await fs.read_file(org, "entities/note.md", snapshot_id=None) is None
    # but the build snapshot still has it (immutable history)
    assert await fs.read_file(org, "entities/note.md", snapshot_id=new_id) == "hello world"


@pytest.mark.parametrize("store", BACKENDS, indirect=True)
async def test_write_file_edits_live_and_snapshots(store):
    fs, _backend_name = store
    org = "acme"
    await fs.ensure(org)

    # write a brand-new nested file: parent dirs are created, an edit snapshot
    # is recorded, and it becomes the latest (consistent) view
    sid = await fs.write_file(org, "entities/repo/acme__web/OVERVIEW.md", "# acme/web\n")
    latest = await fs.latest_snapshot(org)
    assert latest is not None and latest.id == sid and latest.kind == "edit"
    assert await fs.read_file(org, "entities/repo/acme__web/OVERVIEW.md") == "# acme/web\n"
    assert await fs.read_file(org, "entities/repo/acme__web/OVERVIEW.md", snapshot_id=sid) == (
        "# acme/web\n"
    )

    # overwrite an existing seeded file: content is replaced, not appended
    await fs.write_file(org, "INDEX.md", "# rewritten index\n")
    assert await fs.read_file(org, "INDEX.md") == "# rewritten index\n"


def test_at_least_one_backend():
    assert "git" in BACKENDS  # sanity: tests actually ran a backend
