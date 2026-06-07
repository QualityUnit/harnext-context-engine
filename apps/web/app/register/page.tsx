"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { setSession } from "@/lib/auth";
import { Button, Card, Field, inputCls } from "@/components/ui";
import { GoogleButton } from "@/components/GoogleButton";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token, user } = await api.register(email.trim(), password, name.trim());
      setSession(token, user);
      router.replace("/projects");
    } catch (err) {
      const msg = String(err);
      setError(msg.includes("409") ? "That email is already registered." : "Could not create account. Password must be 6+ characters.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-md">
      <Card title="Create account">
        <div className="flex flex-col gap-4">
          <GoogleButton />
          <div className="flex items-center gap-3 text-xs text-neutral-600">
            <span className="h-px flex-1 bg-neutral-800" /> or <span className="h-px flex-1 bg-neutral-800" />
          </div>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <Field label="Name">
              <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada Lovelace" />
            </Field>
            <Field label="Email">
              <input className={inputCls} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required />
            </Field>
            <Field label="Password">
              <input className={inputCls} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="6+ characters" required />
            </Field>
            {error && <p className="text-sm text-red-400">{error}</p>}
            <Button type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create account"}
            </Button>
          </form>
          <p className="text-sm text-neutral-400">
            Already have an account? <Link href="/login" className="text-neutral-200 underline">Sign in</Link>
          </p>
        </div>
      </Card>
    </div>
  );
}
