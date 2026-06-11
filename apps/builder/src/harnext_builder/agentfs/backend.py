"""The FS backend seam.

A backend owns *how* an org's context filesystem is stored and how a build runs
against it. The build itself is always a subprocess command executed with the
org FS as its working directory (the harness-runner) — so the backend is
agnostic to which coding harness runs, and the harness abstraction stays
in-process inside that subprocess.

Two backends:
  - AgentFsBackend (default) — Turso AgentFS SQLite ``.db`` per org, mounted via
    ``agentfs exec``; snapshots are ``cp`` of the ``.db``.
  - GitBackend — a git-backed directory per org; snapshots are commits. No
    external binary, so it powers the tests.

Both are selected by ``BuilderSettings.agentfs_backend``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


def as_text(v: str | bytes | None) -> str:
    """Coerce subprocess output (str with text=True, but bytes per type stubs on
    TimeoutExpired) to a plain string."""
    if v is None:
        return ""
    return v.decode(errors="replace") if isinstance(v, bytes) else v


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@runtime_checkable
class FsBackend(Protocol):
    """Storage + execution for one org's context filesystem."""

    name: str

    def exists(self, org_id: str) -> bool:
        """True if this org already has a store."""
        ...

    def ensure_seeded(self, org_id: str, seed_files: dict[str, str]) -> None:
        """Create the store if missing and write the genesis ``seed_files``.
        Idempotent: a no-op if the store already exists."""
        ...

    def run_build(
        self, org_id: str, command: list[str], env: dict[str, str], timeout_s: int
    ) -> RunResult:
        """Execute ``command`` with the org FS as its working directory,
        mutating the FS in place. Returns the process result."""
        ...

    def snapshot(self, org_id: str, snapshot_id: str) -> str:
        """Capture the current FS state; return a backend-specific ref string
        (stored in FsSnapshot.ref)."""
        ...

    def restore(self, org_id: str, ref: str) -> None:
        """Roll the live FS back to a previously captured snapshot ref."""
        ...

    def read_file(self, org_id: str, relpath: str, ref: str | None = None) -> str | None:
        """Read one file from the live FS (ref=None) or a snapshot ref."""
        ...

    def write_file(self, org_id: str, relpath: str, content: str) -> None:
        """Write ``content`` to ``relpath`` in the live FS, creating parent
        directories and overwriting any existing file. Snapshotting the result
        is the store's responsibility (see OrgFsStore.write_file)."""
        ...

    def list_files(self, org_id: str, ref: str | None = None) -> list[str]:
        """List all file paths in the live FS (ref=None) or a snapshot ref."""
        ...


def get_backend(settings) -> FsBackend:  # type: ignore[no-untyped-def]
    """Construct the configured backend from BuilderSettings."""
    from pathlib import Path

    root = Path(settings.agentfs_dir).resolve()
    if settings.agentfs_backend == "git":
        from harnext_builder.agentfs.git_backend import GitBackend

        return GitBackend(root)
    if settings.agentfs_backend == "agentfs":
        from harnext_builder.agentfs.agentfs_backend import AgentFsBackend

        return AgentFsBackend(root, agentfs_bin=settings.agentfs_bin)
    raise ValueError(f"unknown AGENTFS_BACKEND: {settings.agentfs_backend!r}")
