"""Git-backed directory backend — one git repo per org.

Snapshots are commits (ref = commit sha); restore is ``reset --hard`` + clean.
No external binary beyond git, so this backend powers the tests and works in any
runtime. The harness runs natively in the worktree.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from meaninggrid_builder.agentfs.backend import RunResult, as_text

_GIT_ID = ["-c", "user.email=builder@cms.local", "-c", "user.name=cms-builder"]


class GitBackend:
    name = "git"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "git").mkdir(parents=True, exist_ok=True)

    def _dir(self, org_id: str) -> Path:
        return self.root / "git" / org_id

    def _git(self, org_id: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self._dir(org_id)), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def exists(self, org_id: str) -> bool:
        return (self._dir(org_id) / ".git").exists()

    def ensure_seeded(self, org_id: str, seed_files: dict[str, str]) -> None:
        if self.exists(org_id):
            return
        d = self._dir(org_id)
        d.mkdir(parents=True, exist_ok=True)
        for rel, content in seed_files.items():
            dst = d / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content)
        self._git(org_id, "init", "-q")
        self._git(org_id, "add", "-A")
        self._git(org_id, *_GIT_ID, "commit", "-q", "-m", "genesis")

    def run_build(
        self, org_id: str, command: list[str], env: dict[str, str], timeout_s: int
    ) -> RunResult:
        try:
            p = subprocess.run(
                command,
                cwd=self._dir(org_id),
                env={**os.environ, **env},
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            return RunResult(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired as e:
            return RunResult(124, as_text(e.stdout), as_text(e.stderr), timed_out=True)

    def snapshot(self, org_id: str, snapshot_id: str) -> str:
        self._git(org_id, "add", "-A")
        self._git(org_id, *_GIT_ID, "commit", "-q", "--allow-empty", "-m", snapshot_id)
        return self._git(org_id, "rev-parse", "HEAD").stdout.strip()

    def restore(self, org_id: str, ref: str) -> None:
        self._git(org_id, "reset", "-q", "--hard", ref)
        self._git(org_id, "clean", "-fdq")

    def read_file(self, org_id: str, relpath: str, ref: str | None = None) -> str | None:
        if ref:
            p = subprocess.run(
                ["git", "-C", str(self._dir(org_id)), "show", f"{ref}:{relpath}"],
                capture_output=True,
                text=True,
            )
            return p.stdout if p.returncode == 0 else None
        f = self._dir(org_id) / relpath
        return f.read_text() if f.exists() else None

    def write_file(self, org_id: str, relpath: str, content: str) -> None:
        dst = self._dir(org_id) / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)

    def list_files(self, org_id: str, ref: str | None = None) -> list[str]:
        if ref:
            out = subprocess.run(
                ["git", "-C", str(self._dir(org_id)), "ls-tree", "-r", "--name-only", ref],
                capture_output=True,
                text=True,
            ).stdout
            return [line.strip() for line in out.splitlines() if line.strip()]
        d = self._dir(org_id)
        files: list[str] = []
        for p in d.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
                files.append(str(p.relative_to(d)))
        return files
