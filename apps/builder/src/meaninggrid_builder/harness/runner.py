"""Builder harness runner — executed as a subprocess *inside* the mounted org FS.

The FS backend runs this with the org context filesystem as the working
directory (``agentfs exec`` for AgentFS, plain cwd for git). It:

  1. reads a HarnessRequest from ``$REQUEST_PATH`` (absolute host path),
  2. snapshots file hashes of the working dir,
  3. runs the selected harness in-process (it edits files here),
  4. recomputes the file hashes → ``files_changed`` (truth from the FS),
  5. writes the ConversationTranscript JSON to ``$RESULT_PATH`` (absolute host path).

Exit code 0 unless the harness reported a hard error.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path

from meaninggrid_builder.harness.base import HarnessRequest
from meaninggrid_builder.harness.registry import get_harness

_EXCLUDE_DIRS = {".git", ".agentfs"}


def _walk_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                pass
    return out


def _diff(pre: dict[str, str], post: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for k in sorted(post):
        if k not in pre:
            changed.append(f"A {k}")
        elif pre[k] != post[k]:
            changed.append(f"M {k}")
    for k in sorted(pre):
        if k not in post:
            changed.append(f"D {k}")
    return changed


async def _run(req: HarnessRequest):
    root = Path(req.working_dir)
    pre = _walk_hashes(root)
    transcript = await get_harness(req.harness).run(req)
    post = _walk_hashes(root)
    transcript.files_changed = _diff(pre, post)
    return transcript


def main() -> None:
    req = HarnessRequest.model_validate_json(Path(os.environ["REQUEST_PATH"]).read_text())
    req.working_dir = os.getcwd()  # the mounted FS that the backend set as cwd
    transcript = asyncio.run(_run(req))
    Path(os.environ["RESULT_PATH"]).write_text(transcript.model_dump_json())
    sys.exit(0 if transcript.ok else 1)


if __name__ == "__main__":
    main()
