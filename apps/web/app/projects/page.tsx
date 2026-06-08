"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, fetcher, type Project } from "@/lib/api";
import { clearSession, useUser } from "@/lib/auth";
import { Icon } from "@/components/DashIcons";

export default function ProjectsIndexPage() {
  const user = useUser();
  const router = useRouter();
  const { data: projects, mutate } = useSWR<Project[]>(user ? "/projects" : null, fetcher);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  // Once projects load, hop straight into the first one's dashboard.
  useEffect(() => {
    if (projects && projects.length > 0) router.replace(`/projects/${projects[0].id}`);
  }, [projects, router]);

  if (!user) return null;
  if (!projects) return <div className="firstrun" />;
  if (projects.length > 0) return <div className="firstrun" />; // redirecting

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const p = await api.createProject(name.trim());
      await mutate();
      router.replace(`/projects/${p.id}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="firstrun">
      <div className="firstrun-card">
        <div className="brand" style={{ padding: 0, marginBottom: 18 }}>
          <span className="brand-mark">
            <span className="brand-grid" />
          </span>
          <span className="brand-name">MeaningGrid</span>
          <span className="brand-badge">OSS</span>
          <button className="user-logout" style={{ marginLeft: "auto" }} title="Log out" onClick={() => { clearSession(); router.replace("/login"); }}>
            <Icon.logout size={15} />
          </button>
        </div>
        <h1 className="view-title">Create your first project</h1>
        <p className="view-desc" style={{ marginBottom: 18 }}>
          A project is one context grid — connect GitHub, Slack or Discord and your agents query it over MCP.
        </p>
        <form onSubmit={create}>
          <label className="field-label">Project name</label>
          <div className="field">
            <span className="field-ic">
              <Icon.sources size={15} />
            </span>
            <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="acme-engineering" />
          </div>
          <button className="btn primary lg" type="submit" disabled={busy || !name.trim()} style={{ marginTop: 16, width: "100%", justifyContent: "center" }}>
            <Icon.plus size={16} />
            {busy ? "Creating…" : "Create project"}
          </button>
        </form>
      </div>
    </div>
  );
}
