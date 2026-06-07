"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { api, fetcher, type Project } from "@/lib/api";
import { useUser } from "@/lib/auth";
import { Badge, Button, Card, Field, inputCls } from "@/components/ui";

export default function ProjectsPage() {
  const user = useUser();
  const { data: projects, mutate } = useSWR<Project[]>(
    user ? `/projects?owner_id=${user.id}` : null,
    fetcher,
  );
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  if (!user) return null; // loading or redirecting to /login

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!user || !name.trim()) return;
    setBusy(true);
    try {
      await api.createProject(user.id, name.trim());
      setName("");
      mutate();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card title="New project">
        <form onSubmit={create} className="flex items-end gap-3">
          <div className="flex-1">
            <Field label="Project name">
              <input
                className={inputCls}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme engineering"
              />
            </Field>
          </div>
          <Button type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create project"}
          </Button>
        </form>
      </Card>

      <Card title="Your projects">
        {!projects?.length ? (
          <p className="text-sm text-neutral-500">
            No projects yet. Create one above, then connect GitHub or Slack.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-neutral-800">
            {projects.map((p) => (
              <li key={p.id}>
                <Link
                  href={`/projects/${p.id}`}
                  className="flex items-center justify-between py-3 transition hover:opacity-80"
                >
                  <span className="font-medium">{p.name}</span>
                  <span className="flex items-center gap-2">
                    {p.github_connected && <Badge value="github" />}
                    {p.slack_connected && <Badge value="slack" />}
                    <span className="text-neutral-600">→</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
