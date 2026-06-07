"use client";

import { useState } from "react";
import { createSource } from "@/lib/api";
import { Button, Field, inputCls } from "@/components/ui";

export function AddSourceForm({ orgId, onAdded }: { orgId: string; onAdded: () => void }) {
  const [kind, setKind] = useState("github");
  const [repo, setRepo] = useState("");
  const [channelId, setChannelId] = useState("");
  const [channelName, setChannelName] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const config =
        kind === "github"
          ? { repo }
          : { channel_id: channelId, channel_name: channelName || channelId };
      await createSource({ org_id: orgId, kind, config, secret: secret || null });
      setRepo("");
      setChannelId("");
      setChannelName("");
      setSecret("");
      onAdded();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4">
        <Field label="Kind">
          <select value={kind} onChange={(e) => setKind(e.target.value)} className={inputCls}>
            <option value="github">GitHub</option>
            <option value="slack">Slack</option>
          </select>
        </Field>
        {kind === "github" ? (
          <Field label="Repo (owner/name)">
            <input className={inputCls} value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="vercel/swr" required />
          </Field>
        ) : (
          <Field label="Channel ID">
            <input className={inputCls} value={channelId} onChange={(e) => setChannelId(e.target.value)} placeholder="C0123456" required />
          </Field>
        )}
      </div>
      {kind === "slack" && (
        <Field label="Channel name (optional)">
          <input className={inputCls} value={channelName} onChange={(e) => setChannelName(e.target.value)} placeholder="general" />
        </Field>
      )}
      <Field label={kind === "github" ? "GitHub token (optional for public repos)" : "Slack bot token"}>
        <input className={inputCls} value={secret} onChange={(e) => setSecret(e.target.value)} type="password" placeholder={kind === "slack" ? "xoxb-…" : "ghp_… (optional)"} />
      </Field>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Connecting…" : "Connect source"}
        </Button>
      </div>
    </form>
  );
}
