"use client";

import { useEffect, useRef, useState } from "react";
import useSWR, { mutate as swrMutate } from "swr";
import { api, fetcher, type Project, type Skill, type SkillEncoding, type SkillFileIn } from "@/lib/api";
import { rel } from "@/lib/sourceDisplay";
import { Icon } from "@/components/DashIcons";

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

// Mirrors the server-side slug rule for skill names (they become directory
// names and skill:// URIs, so the API rejects anything else).
const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

// Additional-file paths must be relative POSIX, with the same restrictions the
// API enforces. SKILL.md has its own dedicated editor above the file rows.
function pathError(path: string): string | null {
  if (!path) return null; // an untouched empty row just blocks saving
  if (path.startsWith("/")) return "Path must be relative (no leading /).";
  if (path.includes("..")) return "Path must not contain “..”.";
  if (path.includes("\\")) return "Use forward slashes, not backslashes.";
  if (/[#?%]/.test(path)) return "Path must not contain #, ? or %.";
  const base = path.split("/").pop();
  if (base === "_manifest") return "“_manifest” is reserved.";
  if (path === "SKILL.md") return "SKILL.md is edited above.";
  if (base === "SKILL.md") return "SKILL.md is only allowed at the skill root.";
  return null;
}

// One editable row in the additional-files editor. Binary files (returned
// base64-encoded by the API) are preserved as-is rather than edited as text.
type FileRow = {
  path: string;
  content: string;
  encoding: SkillEncoding;
};

const SKILL_MD_PLACEHOLDER = `---
description: When and how an agent should use this skill
---

# my-skill

Step-by-step instructions the agent follows…`;

// ---- skill card ------------------------------------------------------------
function SkillCard({
  s,
  onEdit,
  onRemove,
}: {
  s: Skill;
  onEdit: (id: string) => void;
  onRemove: (s: Skill) => void;
}) {
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  return (
    <div className="src-card" ref={ref}>
      <div className="src-top">
        <span className="src-ic skill">
          <Icon.zap size={18} />
        </span>
        <div className="src-id">
          <span className="src-name">{s.name}</span>
          <span className="src-sub">
            <Icon.files size={11} />
            {s.files.length} {s.files.length === 1 ? "file" : "files"}
          </span>
        </div>
        <button className="icon-btn" onClick={() => setMenu((m) => !m)} title="Skill actions">
          <Icon.dots size={16} />
        </button>
        {menu && (
          <div className="src-menu">
            <button
              onClick={() => {
                setMenu(false);
                onEdit(s.id);
              }}
            >
              <Icon.file size={14} />
              Edit
            </button>
            <button
              className="danger"
              onClick={() => {
                setMenu(false);
                onRemove(s);
              }}
            >
              <Icon.trash size={14} />
              Delete
            </button>
          </div>
        )}
      </div>

      <p className="skill-desc">{s.description || "No description yet."}</p>

      <div className="src-foot">
        <span className="pill mut">
          <span className="pill-dot" />
          skill
        </span>
        <span className="src-sync">updated {rel(s.updated_at)}</span>
      </div>
    </div>
  );
}

// ---- create / edit modal ---------------------------------------------------
function SkillModal({
  project,
  skillId,
  onClose,
  onSaved,
}: {
  project: Project;
  skillId: string | null; // null = create
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = skillId !== null;
  // Edit loads the full skill (file contents included) before the form opens up.
  const existing = useSWR<Skill>(editing ? `/skills/${skillId}` : null, fetcher, {
    revalidateOnFocus: false,
  });

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [skillMd, setSkillMd] = useState("");
  const [files, setFiles] = useState<FileRow[]>([]);
  const [hydrated, setHydrated] = useState(!editing);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Fill the form once the existing skill arrives (and never again, so a
  // background revalidation can't clobber in-progress edits).
  useEffect(() => {
    if (!editing || hydrated || !existing.data) return;
    const sk = existing.data;
    setName(sk.name);
    setDescription(sk.description);
    setSkillMd(sk.files.find((f) => f.path === "SKILL.md")?.content ?? "");
    setFiles(
      sk.files
        .filter((f) => f.path !== "SKILL.md")
        .map((f) => ({ path: f.path, content: f.content ?? "", encoding: f.encoding ?? "utf-8" })),
    );
    setHydrated(true);
  }, [editing, hydrated, existing.data]);

  const nameOk = NAME_RE.test(name.trim());
  const fileErrs = files.map((f) => pathError(f.path.trim()));
  const paths = files.map((f) => f.path.trim());
  const dupPaths = new Set(paths.filter((p, i) => p && paths.indexOf(p) !== i));
  const valid =
    nameOk &&
    skillMd.trim().length > 0 &&
    fileErrs.every((e) => e === null) &&
    paths.every((p) => p.length > 0) &&
    dupPaths.size === 0;

  const setRow = (i: number, patch: Partial<FileRow>) =>
    setFiles((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const addRow = () => setFiles((rows) => [...rows, { path: "", content: "", encoding: "utf-8" }]);
  const removeRow = (i: number) => setFiles((rows) => rows.filter((_, j) => j !== i));

  async function save() {
    if (!valid || busy) return;
    setBusy(true);
    setErr(null);
    const body: SkillFileIn[] = [
      { path: "SKILL.md", content: skillMd, encoding: "utf-8" },
      ...files.map((f) => ({ path: f.path.trim(), content: f.content, encoding: f.encoding })),
    ];
    try {
      if (editing) await api.updateSkill(skillId, description.trim(), body);
      else await api.createSkill(project.id, name.trim(), description.trim(), body);
    } catch (e) {
      setErr(errMsg(e));
      setBusy(false);
      return;
    }
    // Drop the cached GET /skills/{id} so reopening the editor refetches.
    if (editing) void swrMutate(`/skills/${skillId}`);
    onSaved();
    onClose();
  }

  return (
    <div className="modal-wrap" onMouseDown={onClose}>
      <div className="modal wide" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{editing ? "Edit skill" : "Create a skill"}</h3>
          <button className="icon-btn" onClick={onClose}>
            <Icon.x size={16} />
          </button>
        </div>

        {editing && !hydrated ? (
          <div className="modal-body">
            {existing.error ? (
              <p className="modal-err">{errMsg(existing.error)}</p>
            ) : (
              <p className="modal-note">Loading skill…</p>
            )}
            <div className="modal-actions">
              <button className="btn ghost" onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        ) : (
          <div className="modal-body scroll">
            <label className="field-label">Name</label>
            <div className={"field" + (name && !nameOk ? " bad" : "")}>
              <span className="field-ic">
                <Icon.zap size={15} />
              </span>
              <input
                autoFocus={!editing}
                value={name}
                disabled={editing}
                onChange={(e) => setName(e.target.value)}
                placeholder="code-review"
              />
            </div>
            {name && !nameOk && (
              <p className="field-err">
                <Icon.alert size={12} />
                Lowercase letters, digits, “-” and “_” only; must start with a letter or digit (max 64
                chars).
              </p>
            )}

            <label className="field-label" style={{ marginTop: 12 }}>
              Description <span style={{ color: "var(--tx-3)" }}>· optional</span>
            </label>
            <div className="field">
              <span className="field-ic">
                <Icon.file size={15} />
              </span>
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="When should an agent reach for this skill?"
              />
            </div>
            <p className="modal-note">
              Leave blank to use the <code className="ic">description</code> from SKILL.md&apos;s YAML
              frontmatter (or its first line of text).
            </p>

            <label className="field-label" style={{ marginTop: 12 }}>
              SKILL.md
            </label>
            <textarea
              className="skill-text"
              value={skillMd}
              onChange={(e) => setSkillMd(e.target.value)}
              spellCheck={false}
              placeholder={SKILL_MD_PLACEHOLDER}
            />

            <label className="field-label" style={{ marginTop: 14 }}>
              Additional files <span style={{ color: "var(--tx-3)" }}>· optional</span>
            </label>
            {files.map((f, i) => {
              const perr = fileErrs[i] ?? (dupPaths.has(f.path.trim()) ? "Duplicate path." : null);
              const binary = f.encoding === "base64";
              return (
                <div className="skill-file" key={i}>
                  <div className="skill-file-head">
                    <div className={"field" + (perr ? " bad" : "")}>
                      <span className="field-ic">
                        <Icon.file size={14} />
                      </span>
                      <input
                        value={f.path}
                        onChange={(e) => setRow(i, { path: e.target.value })}
                        placeholder="scripts/run.py"
                      />
                    </div>
                    <button className="icon-btn" title="Remove file" onClick={() => removeRow(i)}>
                      <Icon.trash size={15} />
                    </button>
                  </div>
                  {perr && (
                    <p className="field-err" style={{ marginBottom: 8 }}>
                      <Icon.alert size={12} />
                      {perr}
                    </p>
                  )}
                  {binary ? (
                    <p className="modal-note" style={{ marginTop: 0 }}>
                      Binary file ({f.content.length.toLocaleString()} base64 chars) — kept as-is when
                      you save.
                    </p>
                  ) : (
                    <textarea
                      className="skill-text sm"
                      value={f.content}
                      onChange={(e) => setRow(i, { content: e.target.value })}
                      spellCheck={false}
                      placeholder="file contents…"
                    />
                  )}
                </div>
              );
            })}
            <button className="btn ghost" style={{ marginTop: 10 }} onClick={addRow}>
              <Icon.plus size={14} />
              Add file
            </button>

            {err && <p className="modal-err">{err}</p>}
            <div className="modal-actions">
              <button className="btn ghost" onClick={onClose}>
                Cancel
              </button>
              <button className="btn primary" disabled={busy || !valid} onClick={() => void save()}>
                <Icon.save size={14} />
                {busy ? "Saving…" : editing ? "Save changes" : "Create skill"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---- view ------------------------------------------------------------------
export function SkillsView({ project }: { project: Project }) {
  const skills = useSWR<Skill[]>(`/skills?project_id=${project.id}`, fetcher);
  const [modal, setModal] = useState<{ skillId: string | null } | null>(null);

  const onRemove = async (s: Skill) => {
    if (!window.confirm(`Delete the “${s.name}” skill? Agents will no longer see it.`)) return;
    try {
      await api.deleteSkill(s.id);
    } catch (e) {
      alert(`Could not delete skill: ${errMsg(e)}`);
    }
    skills.mutate();
  };

  const list = skills.data ?? [];

  return (
    <div className="view">
      <div className="view-head">
        <div>
          <div className="crumb">
            {project.name}
            <span className="crumb-sep">/</span>
            <span>skills</span>
          </div>
          <h1 className="view-title">Skills</h1>
          <p className="view-desc">
            Reusable instruction packs every agent working on <b>{project.name}</b> shares — a SKILL.md
            plus any helper files, served over MCP and materialized into each agent&apos;s working
            directory.
          </p>
        </div>
        <button className="btn primary lg" onClick={() => setModal({ skillId: null })}>
          <Icon.plus size={16} />
          New skill
        </button>
      </div>

      <div className="src-grid">
        {list.map((s) => (
          <SkillCard key={s.id} s={s} onEdit={(id) => setModal({ skillId: id })} onRemove={onRemove} />
        ))}
        <button className="src-card add" onClick={() => setModal({ skillId: null })}>
          <span className="add-plus">
            <Icon.plus size={20} />
          </span>
          <span className="add-label">{!skills.data && !skills.error ? "Loading…" : "New skill"}</span>
          <span className="add-sub">A SKILL.md with optional scripts and reference files</span>
        </button>
      </div>
      {skills.error && <p className="modal-err">{errMsg(skills.error)}</p>}

      {modal && (
        <SkillModal
          project={project}
          skillId={modal.skillId}
          onClose={() => setModal(null)}
          onSaved={() => skills.mutate()}
        />
      )}
    </div>
  );
}
