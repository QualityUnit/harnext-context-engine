"""skills_fs helpers: SKILL.md description parsing, file metadata, materialization."""

import hashlib
from uuid import uuid4

from harnext_shared import (
    Project,
    Skill,
    SkillFile,
    User,
    init_db,
    make_engine,
    make_sessionmaker,
    materialize_skills,
    parse_skill_description,
    skill_file_meta,
)

# --- parse_skill_description -------------------------------------------------


def test_description_from_frontmatter():
    md = '---\nname: pdf\ndescription: "Turn PDFs into text"\n---\n\n# PDF\n\nBody line.\n'
    assert parse_skill_description(md) == "Turn PDFs into text"


def test_description_no_frontmatter_uses_first_non_heading_line():
    md = "# PDF tools\n\nTurn PDFs into text.\nMore prose.\n"
    assert parse_skill_description(md) == "Turn PDFs into text."


def test_description_frontmatter_without_description_falls_through_to_body():
    md = "---\nname: pdf\n---\nProse first.\n"
    assert parse_skill_description(md) == "Prose first."


def test_description_heading_only_falls_back_to_heading_text():
    assert parse_skill_description("# Only a heading\n") == "Only a heading"


def test_description_empty_skill_md():
    assert parse_skill_description("") == ""


def test_description_unclosed_frontmatter_is_treated_as_body():
    # No closing fence -> not frontmatter (mirrors fastmcp's parser).
    md = "---\ndescription: nope"
    assert parse_skill_description(md) == "---"


# --- skill_file_meta ----------------------------------------------------------


def test_skill_file_meta_markdown_and_hash():
    content = b"# hi\n"
    mime, size, digest = skill_file_meta("SKILL.md", content)
    assert mime == "text/markdown"
    assert size == len(content)
    assert digest == "sha256:" + hashlib.sha256(content).hexdigest()


def test_skill_file_meta_guesses_and_defaults():
    assert skill_file_meta("data/cfg.json", b"{}")[0] == "application/json"
    assert skill_file_meta("blob.xyz123", b"\x00\x01")[0] == "application/octet-stream"


# --- materialize_skills -------------------------------------------------------


async def _seeded_db(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)  # alembic upgrade head — creates skills/skill_files
    sm = make_sessionmaker(engine)
    async with sm() as s:
        user = User(id=uuid4().hex, email="a@b.com")
        s.add(user)
        await s.flush()  # no ORM relationships -> flush the FK target first
        proj = Project(id=uuid4().hex, name="P", owner_id=user.id)
        other = Project(id=uuid4().hex, name="Q", owner_id=user.id)
        s.add_all([proj, other])
        await s.commit()
    return engine, sm, proj.id, other.id


def _file(skill_id: str, path: str, content: bytes) -> SkillFile:
    mime, size, digest = skill_file_meta(path, content)
    return SkillFile(
        id=uuid4().hex,
        skill_id=skill_id,
        path=path,
        mime_type=mime,
        size=size,
        hash=digest,
        content=content,
    )


async def test_materialize_writes_tree_scoped_to_org(tmp_path):
    engine, sm, org, other_org = await _seeded_db(tmp_path)
    try:
        async with sm() as s:
            skill = Skill(id=uuid4().hex, org_id=org, name="pdf", description="d")
            foreign = Skill(id=uuid4().hex, org_id=other_org, name="alien", description="")
            s.add_all([skill, foreign])
            await s.flush()
            s.add_all(
                [
                    _file(skill.id, "SKILL.md", b"# PDF\n\nProcess PDFs.\n"),
                    _file(skill.id, "scripts/run.py", b"print('hi')\n"),
                    _file(foreign.id, "SKILL.md", b"# alien\n"),
                ]
            )
            await s.commit()

        dest = tmp_path / "work"
        dirs = await materialize_skills(sm, org, dest)

        root = dest / ".claude" / "skills"
        assert dirs == [root / "pdf"]
        assert (root / "pdf" / "SKILL.md").read_bytes() == b"# PDF\n\nProcess PDFs.\n"
        assert (root / "pdf" / "scripts" / "run.py").read_bytes() == b"print('hi')\n"
        assert not (root / "alien").exists()  # other org's skill never materialized
    finally:
        await engine.dispose()


async def test_materialize_skips_traversal_unsafe_paths(tmp_path):
    engine, sm, org, _ = await _seeded_db(tmp_path)
    try:
        async with sm() as s:
            skill = Skill(id=uuid4().hex, org_id=org, name="sneaky", description="")
            s.add(skill)
            await s.flush()
            s.add_all(
                [
                    _file(skill.id, "SKILL.md", b"# ok\n"),
                    _file(skill.id, "../escape.txt", b"x"),
                    _file(skill.id, "/abs.txt", b"x"),
                    _file(skill.id, "a\\b.txt", b"x"),
                    _file(skill.id, "nested/../../escape2.txt", b"x"),
                ]
            )
            await s.commit()

        dest = tmp_path / "work"
        dirs = await materialize_skills(sm, org, dest)

        skill_dir = dest / ".claude" / "skills" / "sneaky"
        assert dirs == [skill_dir]
        # only the safe file lands; nothing escapes the skill dir
        assert [p.name for p in skill_dir.rglob("*") if p.is_file()] == ["SKILL.md"]
        assert not (tmp_path / "escape.txt").exists()
        assert not (dest / ".claude" / "escape2.txt").exists()
    finally:
        await engine.dispose()


async def test_materialize_survives_file_dir_path_collision(tmp_path):
    """A row set where one path is another's directory ("SKILL.md" +
    "SKILL.md/extra.txt") must be skipped, not raised — one bad skill must
    never break the org's builds, and later skills still materialize."""
    engine, sm, org, _ = await _seeded_db(tmp_path)
    try:
        async with sm() as s:
            clash = Skill(id=uuid4().hex, org_id=org, name="clash", description="")
            good = Skill(id=uuid4().hex, org_id=org, name="good", description="")
            s.add_all([clash, good])
            await s.flush()
            s.add_all(
                [
                    _file(clash.id, "SKILL.md", b"# clash\n"),
                    _file(clash.id, "SKILL.md/extra.txt", b"x"),  # parent is a FILE
                    _file(clash.id, "a/b.txt", b"y"),
                    _file(clash.id, "a/b.txt/c.txt", b"z"),
                    _file(good.id, "SKILL.md", b"# good\n"),
                ]
            )
            await s.commit()

        dest = tmp_path / "work"
        dirs = await materialize_skills(sm, org, dest)  # must not raise

        root = dest / ".claude" / "skills"
        assert dirs == [root / "clash", root / "good"]
        # the colliding rows are skipped; everything else still lands
        assert (root / "clash" / "SKILL.md").read_bytes() == b"# clash\n"
        assert (root / "clash" / "a" / "b.txt").read_bytes() == b"y"
        assert (root / "good" / "SKILL.md").read_bytes() == b"# good\n"
    finally:
        await engine.dispose()


async def test_materialize_no_skills_is_a_noop(tmp_path):
    engine, sm, org, _ = await _seeded_db(tmp_path)
    try:
        dest = tmp_path / "work"
        assert await materialize_skills(sm, org, dest) == []
        assert not (dest / ".claude").exists()
    finally:
        await engine.dispose()
