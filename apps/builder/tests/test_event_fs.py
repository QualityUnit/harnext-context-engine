"""The `_event/` mount: layout, manifest, traversal guards, prompt redaction."""

from datetime import UTC, datetime

from harnext_builder.event_fs import EVENT_DIR, MANIFEST, event_files, rel_for, safe_id
from harnext_builder.prompts import render_instruction
from harnext_builder.work_item import WorkItem
from harnext_shared import CloudEvent


def _commit(eid="github-commit-acme/web-abc", files=None) -> CloudEvent:
    data = {"sha": "abc", "message": "fix", "author": "ada"}
    if files is not None:
        data["files"] = files
    return CloudEvent(
        id=eid,
        source="github:acme/web",
        type="com.github.commit",
        subject="repo:acme/web",
        time=datetime.now(UTC),
        mgtenant="acme",
        data=data,
    )


def test_event_files_layout_and_manifest():
    ev = _commit(
        files=[
            {"path": "src/app.py", "status": "modified", "content": "print('hi')\n"},
            {"path": "README.md", "status": "added", "content": "# hi\n", "truncated": True},
            {"path": "gone.txt", "status": "removed"},  # no content -> not written
        ]
    )
    out = event_files([ev])
    by_path = {ef.path: ef.content for ef in out}

    sid = safe_id(ev.id)
    assert by_path[f"{EVENT_DIR}/{sid}/src/app.py"] == "print('hi')\n"
    assert by_path[f"{EVENT_DIR}/{sid}/README.md"] == "# hi\n"
    # removed file gets no materialized file
    assert not any(p.endswith("gone.txt") for p in by_path)

    manifest = by_path[MANIFEST]
    assert "src/app.py" in manifest and "(truncated)" in manifest
    assert "gone.txt" in manifest and "no content" in manifest


def test_event_files_empty_without_content():
    assert event_files([_commit(files=None)]) == []
    assert event_files([_commit(files=[{"path": "x", "status": "removed"}])]) == []


def test_path_traversal_is_rejected():
    ev = _commit(
        files=[
            {"path": "../escape.py", "status": "added", "content": "x"},
            {"path": "/etc/passwd", "status": "added", "content": "x"},
            {"path": "ok.py", "status": "added", "content": "x"},
        ]
    )
    paths = [ef.path for ef in event_files([ev])]
    assert not any(".." in p for p in paths)
    assert not any(p.startswith(f"{EVENT_DIR}//") for p in paths)  # no absolute leak
    assert any(p.endswith("/ok.py") for p in paths)


def test_safe_id_sanitizes_slashes():
    assert "/" not in safe_id("github-commit-acme/web-abc")


def test_prompt_redacts_content_and_points_at_event_dir():
    ev = _commit(
        files=[{"path": "src/app.py", "status": "modified", "content": "SECRET-BODY"}]
    )
    out = render_instruction(WorkItem.from_fast_event(ev))
    # the file body never appears inline; a pointer to its mount does
    assert "SECRET-BODY" not in out
    assert rel_for(ev.id, "src/app.py") in out
    # the file is still named so the agent knows it exists
    assert "src/app.py" in out
