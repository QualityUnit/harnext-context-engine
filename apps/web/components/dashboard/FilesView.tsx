"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type Project } from "@/lib/api";
import { Icon } from "@/components/DashIcons";

// ---- tree model ----------------------------------------------------------
type TreeNode = {
  name: string;
  path: string; // full relpath
  dir: boolean;
  children: TreeNode[];
};

// Turn the flat list of relpaths the API returns into a nested folder tree.
function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", dir: true, children: [] };
  for (const p of paths) {
    const parts = p.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const isFile = i === parts.length - 1;
      const path = parts.slice(0, i + 1).join("/");
      let child = node.children.find((c) => c.name === part && c.dir === !isFile);
      if (!child) {
        child = { name: part, path, dir: !isFile, children: [] };
        node.children.push(child);
      }
      node = child;
    });
  }
  const sort = (nodes: TreeNode[]) => {
    // folders first, then files, each alphabetically
    nodes.sort((a, b) => (a.dir === b.dir ? a.name.localeCompare(b.name) : a.dir ? -1 : 1));
    nodes.forEach((n) => sort(n.children));
  };
  sort(root.children);
  return root.children;
}

function TreeRow({
  node,
  depth,
  selected,
  collapsed,
  onToggle,
  onOpen,
  dirtyPaths,
}: {
  node: TreeNode;
  depth: number;
  selected: string | null;
  collapsed: Set<string>;
  onToggle: (path: string) => void;
  onOpen: (path: string) => void;
  dirtyPaths: Set<string>;
}) {
  const pad = 10 + depth * 14;
  if (node.dir) {
    const open = !collapsed.has(node.path);
    return (
      <>
        <button className="fs-node dir" style={{ paddingLeft: pad }} onClick={() => onToggle(node.path)}>
          <span className="fs-twist" data-open={open}>
            <Icon.chevronR size={12} />
          </span>
          <Icon.folder size={14} />
          <span className="fs-name">{node.name}</span>
        </button>
        {open &&
          node.children.map((c) => (
            <TreeRow
              key={c.path}
              node={c}
              depth={depth + 1}
              selected={selected}
              collapsed={collapsed}
              onToggle={onToggle}
              onOpen={onOpen}
              dirtyPaths={dirtyPaths}
            />
          ))}
      </>
    );
  }
  return (
    <button
      className={"fs-node file" + (selected === node.path ? " active" : "")}
      style={{ paddingLeft: pad + 16 }}
      onClick={() => onOpen(node.path)}
    >
      <Icon.file size={13} />
      <span className="fs-name">{node.name}</span>
      {dirtyPaths.has(node.path) && <span className="fs-dot" title="Unsaved changes" />}
    </button>
  );
}

export function FilesView({
  project,
  files,
  snapshotId,
  loading,
  onReload,
}: {
  project: Project;
  files: string[];
  snapshotId: string | null;
  loading: boolean;
  onReload: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  // caches keyed by path: the last-saved content, and any in-progress edit
  const [originals, setOriginals] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [loadingPath, setLoadingPath] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  const tree = useMemo(() => buildTree(files), [files]);
  const dirtyPaths = useMemo(
    () => new Set(Object.keys(drafts).filter((p) => drafts[p] !== originals[p])),
    [drafts, originals],
  );

  const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const open = async (path: string) => {
    setSelected(path);
    setStatus(null);
    if (path in originals) return; // already fetched
    setLoadingPath(path);
    try {
      const f = await api.readFile(project.id, path);
      setOriginals((m) => ({ ...m, [path]: f.content }));
    } catch (e) {
      setStatus({ kind: "err", msg: errMsg(e) });
    } finally {
      setLoadingPath((p) => (p === path ? null : p));
    }
  };

  // Auto-open a sensible first file (INDEX.md) so the editor isn't empty.
  useEffect(() => {
    if (selected || files.length === 0) return;
    void open(files.includes("INDEX.md") ? "INDEX.md" : files[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, selected]);

  const original = selected ? originals[selected] : undefined;
  const draft = selected && selected in drafts ? drafts[selected] : original;
  const dirty = selected != null && draft !== undefined && draft !== original;
  const fileLoading = selected != null && loadingPath === selected && original === undefined;

  const onEdit = (v: string) => {
    if (!selected) return;
    setDrafts((m) => ({ ...m, [selected]: v }));
    setStatus(null);
  };

  const save = async () => {
    if (!selected || !dirty || saving) return;
    const body = draft ?? "";
    setSaving(true);
    setStatus(null);
    try {
      await api.writeFile(project.id, selected, body);
      setOriginals((m) => ({ ...m, [selected]: body }));
      setDrafts((m) => {
        const n = { ...m };
        delete n[selected];
        return n;
      });
      setStatus({ kind: "ok", msg: "Saved — the agent now sees this." });
      onReload(); // a newly-created path should appear in the tree
    } catch (e) {
      setStatus({ kind: "err", msg: errMsg(e) });
    } finally {
      setSaving(false);
    }
  };

  const toggle = (path: string) =>
    setCollapsed((c) => {
      const n = new Set(c);
      n.has(path) ? n.delete(path) : n.add(path);
      return n;
    });

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "s") {
      e.preventDefault();
      void save();
    }
  };

  const bytes = draft ? new Blob([draft]).size : 0;
  const lines = draft ? draft.split("\n").length : 0;

  return (
    <div className="view">
      <div className="view-head">
        <div>
          <div className="crumb">
            {project.name}
            <span className="crumb-sep">/</span>
            <span>files</span>
          </div>
          <h1 className="view-title">Context filesystem</h1>
          <p className="view-desc">
            The exact files the builder agent reads and writes for <b>{project.name}</b> — its
            living memory. Edit any file and save to update the context the agent sees.
          </p>
        </div>
      </div>

      <div className="fs-editor" onKeyDown={onKeyDown}>
        <aside className="fs-tree">
          <div className="fs-tree-head">
            <span>
              <Icon.files size={13} /> Explorer
            </span>
            <button className="fs-icon-btn" title="Refresh" onClick={onReload}>
              <Icon.sync size={13} />
            </button>
          </div>
          <div className="fs-tree-body">
            {loading && files.length === 0 ? (
              <div className="fs-tree-empty">Loading…</div>
            ) : files.length === 0 ? (
              <div className="fs-tree-empty">No files yet.</div>
            ) : (
              tree.map((n) => (
                <TreeRow
                  key={n.path}
                  node={n}
                  depth={0}
                  selected={selected}
                  collapsed={collapsed}
                  onToggle={toggle}
                  onOpen={open}
                  dirtyPaths={dirtyPaths}
                />
              ))
            )}
          </div>
          {snapshotId && (
            <div className="fs-tree-foot" title={`Snapshot ${snapshotId}`}>
              snapshot {snapshotId.slice(0, 10)}
            </div>
          )}
        </aside>

        <section className="fs-pane">
          {!selected ? (
            <div className="fs-pane-empty">Select a file to view and edit it.</div>
          ) : (
            <>
              <div className="fs-pane-head">
                <span className="fs-path">
                  <Icon.file size={13} />
                  {selected}
                  {dirty && <span className="fs-dot" />}
                </span>
                <span className="fs-pane-meta">
                  {lines.toLocaleString()} lines · {bytes.toLocaleString()} B
                </span>
                {status && <span className={"fs-status " + status.kind}>{status.msg}</span>}
                <button
                  className="btn primary"
                  onClick={() => void save()}
                  disabled={!dirty || saving}
                >
                  <Icon.save size={14} />
                  {saving ? "Saving…" : "Save"}
                </button>
              </div>
              {fileLoading ? (
                <div className="fs-pane-empty">Loading {selected}…</div>
              ) : (
                <textarea
                  className="fs-text"
                  value={draft ?? ""}
                  onChange={(e) => onEdit(e.target.value)}
                  spellCheck={false}
                  placeholder="(empty file)"
                />
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
