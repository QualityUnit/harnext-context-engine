"""AgentFS backend — Turso AgentFS, one SQLite ``.db`` per org.

Verified CLI surface (agentfs 0.6.x):
  - ``agentfs init <id>``            → creates ``./.agentfs/<id>.db`` (run with cwd=root)
  - ``agentfs exec <db> <cmd...>``   → mounts the db to a temp dir, runs cmd there
                                       with that dir as cwd, auto-unmounts. Not a
                                       chroot — cmd can still touch absolute host paths.
  - ``agentfs fs <db> ls /``         → recursive flat listing (``f``/``d`` <path>)
  - ``agentfs fs <db> cat <path>``   → file contents (no FUSE)
  - snapshot                         → ``cp <db> <snap.db>``
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from meaninggrid_builder.agentfs.backend import RunResult, as_text

_SIDECAR_SUFFIXES = ("-wal", "-shm")


def resolve_agentfs_bin(name: str = "agentfs") -> str:
    """Find the agentfs binary; fall back to the cargo install location."""
    found = shutil.which(name)
    if found:
        return found
    cargo = Path.home() / ".cargo" / "bin" / "agentfs"
    if cargo.exists():
        return str(cargo)
    return name  # let the call fail loudly with a clear error


class AgentFsBackend:
    name = "agentfs"

    def __init__(self, root: Path, agentfs_bin: str = "agentfs") -> None:
        self.root = Path(root)
        self.bin = resolve_agentfs_bin(agentfs_bin)
        (self.root / ".agentfs").mkdir(parents=True, exist_ok=True)
        (self.root / "snapshots").mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------
    def _db(self, org_id: str) -> Path:
        return self.root / ".agentfs" / f"{org_id}.db"

    def _snap_path(self, org_id: str, snapshot_id: str) -> Path:
        return self.root / "snapshots" / org_id / f"{snapshot_id}.db"

    # -- lifecycle ---------------------------------------------------------
    def exists(self, org_id: str) -> bool:
        return self._db(org_id).exists()

    def ensure_seeded(self, org_id: str, seed_files: dict[str, str]) -> None:
        if self.exists(org_id):
            return
        # create the empty FS (init writes ./.agentfs/<org>.db relative to cwd)
        subprocess.run(
            [self.bin, "init", org_id, "--force"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        # stage seed files natively, then import the tree into the FS via cp
        with tempfile.TemporaryDirectory(prefix=f"seed-{org_id}-") as stage:
            stage_p = Path(stage)
            for rel, content in seed_files.items():
                dst = stage_p / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content)
            # `cp -r <stage>/. .` copies contents (incl. dotfiles) into the mount
            self._exec(org_id, ["cp", "-r", f"{stage_p}/.", "."], env={}, timeout_s=60)

    # -- execution ---------------------------------------------------------
    def _exec(
        self, org_id: str, command: list[str], env: dict[str, str], timeout_s: int
    ) -> RunResult:
        full = [self.bin, "exec", str(self._db(org_id)), *command]
        merged = {**os.environ, **env}
        try:
            p = subprocess.run(full, env=merged, capture_output=True, text=True, timeout=timeout_s)
            return RunResult(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired as e:
            return RunResult(124, as_text(e.stdout), as_text(e.stderr), timed_out=True)

    def run_build(
        self, org_id: str, command: list[str], env: dict[str, str], timeout_s: int
    ) -> RunResult:
        return self._exec(org_id, command, env, timeout_s)

    # -- snapshots ---------------------------------------------------------
    def _copy_db(self, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        for suf in _SIDECAR_SUFFIXES:
            side = src.with_name(src.name + suf)
            if side.exists():
                shutil.copy2(side, dst.with_name(dst.name + suf))

    def snapshot(self, org_id: str, snapshot_id: str) -> str:
        dst = self._snap_path(org_id, snapshot_id)
        self._copy_db(self._db(org_id), dst)
        return str(dst)

    def restore(self, org_id: str, ref: str) -> None:
        live = self._db(org_id)
        for suf in _SIDECAR_SUFFIXES:  # clear stale WAL/SHM before restore
            side = live.with_name(live.name + suf)
            if side.exists():
                side.unlink()
        self._copy_db(Path(ref), live)

    # -- reads -------------------------------------------------------------
    def _target(self, org_id: str, ref: str | None) -> str:
        return ref if ref else str(self._db(org_id))

    def read_file(self, org_id: str, relpath: str, ref: str | None = None) -> str | None:
        p = subprocess.run(
            [self.bin, "fs", self._target(org_id, ref), "cat", relpath],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0 or "File not found" in p.stderr:
            return None
        return p.stdout

    def write_file(self, org_id: str, relpath: str, content: str) -> None:
        # Stage the file natively under its relpath, then copy the tree into the
        # mount (`cp -r <stage>/. .`) — same import path as ensure_seeded, so the
        # parent directories are created and an existing file is overwritten.
        with tempfile.TemporaryDirectory(prefix=f"edit-{org_id}-") as stage:
            dst = Path(stage) / relpath
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content)
            res = self._exec(org_id, ["cp", "-r", f"{stage}/.", "."], env={}, timeout_s=60)
            if not res.ok:
                raise RuntimeError(f"agentfs write failed: {res.stderr or res.stdout}")

    def list_files(self, org_id: str, ref: str | None = None) -> list[str]:
        p = subprocess.run(
            [self.bin, "fs", self._target(org_id, ref), "ls", "/"],
            capture_output=True,
            text=True,
        )
        files: list[str] = []
        for line in p.stdout.splitlines():
            if line.startswith("f "):
                files.append(line[2:].strip())
        return files
