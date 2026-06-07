"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { setUser } from "@/lib/auth";
import { Button, Card, Field, inputCls } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const user = await api.login(username.trim());
      setUser(user);
      router.replace("/projects");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-md">
      <Card title="Sign in">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <p className="text-sm text-neutral-400">
            Demo mode — just pick a username to continue. No password.
          </p>
          <Field label="Username">
            <input
              className={inputCls}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="alice"
              autoFocus
            />
          </Field>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <Button type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Continue"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
