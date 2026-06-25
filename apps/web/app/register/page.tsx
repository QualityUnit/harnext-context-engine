"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { IAlert, IArrow, ICheck, IMail, IServer, IUser } from "@/components/Icons";

// Harnext isn't generally available yet. Instead of provisioning accounts, this
// page registers interest in the closed beta: it collects a name + email and
// hands them to Mailchimp (tagged), so we can invite people in waves.
export default function RegisterPage() {
  const [f, setF] = useState({ name: "", email: "" });
  const [errs, setErrs] = useState<{ name?: string | null; email?: string | null }>({});
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  const [formError, setFormError] = useState<string | null>(null);

  const set = (k: "name" | "email") => (v: string) => {
    setF((p) => ({ ...p, [k]: v }));
    setErrs((e) => ({ ...e, [k]: null }));
    setFormError(null);
  };

  async function submit() {
    const e: { name?: string; email?: string } = {};
    if (f.name.trim().length < 2) e.name = "Enter your name";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email)) e.email = "Enter a valid email";
    setErrs(e);
    if (Object.keys(e).length) return;

    setState("loading");
    setFormError(null);
    try {
      await api.betaSignup(f.email.trim(), f.name.trim());
      setState("done");
    } catch {
      setState("idle");
      setFormError("Couldn’t register you right now. Please try again in a moment.");
    }
  }

  const onKey = (ev: React.KeyboardEvent) => {
    if (ev.key === "Enter") submit();
  };

  return (
    <div className="auth">
      <div className="page-grid" aria-hidden="true" />
      <div className="form-card" onKeyDown={onKey}>
        <div className="fc-brand">
          <span className="fc-emblem-mark">
            <span className="brand-grid" />
          </span>
          <div className="fc-wordmark">
            Harnext<span className="fc-oss">OSS</span>
          </div>
        </div>

        {state === "done" ? (
          <div className="success">
            <div className="succ-ic">
              <ICheck />
            </div>
            <div className="succ-title">You’re on the list</div>
            <div className="succ-sub">
              Thanks for your interest in Harnext Context Engine. We’re onboarding new
              users in waves during the closed beta — we’ll email you when it’s your turn.
            </div>
            <Link className="succ-btn" href="/login">
              Back to sign in <IArrow />
            </Link>
          </div>
        ) : (
          <>
            <div className="fc-head">
              <div className="fc-title">Join the closed beta</div>
              <div className="fc-sub">
                Harnext Context Engine is in private testing — we’re inviting new users in
                small batches. Leave your details and we’ll reach out with an invite.
              </div>
            </div>

            <div className="field-group">
              <div>
                <div className="field-label">
                  <span>Name</span>
                </div>
                <div className={"field" + (errs.name ? " bad" : "")}>
                  <span className="field-ic">
                    <IUser />
                  </span>
                  <input
                    value={f.name}
                    autoFocus
                    onChange={(e) => set("name")(e.target.value)}
                    placeholder="Ada Lovelace"
                  />
                </div>
                {errs.name && (
                  <div className="field-err">
                    <IAlert />
                    {errs.name}
                  </div>
                )}
              </div>

              <div>
                <div className="field-label">
                  <span>Email</span>
                </div>
                <div className={"field" + (errs.email ? " bad" : "")}>
                  <span className="field-ic">
                    <IMail />
                  </span>
                  <input
                    type="email"
                    value={f.email}
                    onChange={(e) => set("email")(e.target.value)}
                    placeholder="dev@acme.io"
                  />
                </div>
                {errs.email && (
                  <div className="field-err">
                    <IAlert />
                    {errs.email}
                  </div>
                )}
              </div>
            </div>

            {formError && (
              <div className="field-err" style={{ justifyContent: "center", marginTop: 14 }}>
                <IAlert />
                {formError}
              </div>
            )}

            <button className="submit" onClick={submit} disabled={state === "loading"}>
              {state === "loading" ? (
                <span className="spin" />
              ) : (
                <>
                  Request an invite
                  <IArrow />
                </>
              )}
            </button>

            <div className="toggle">
              Already have an account?{" "}
              <Link href="/login">Sign in</Link>
            </div>

            <div className="selfhost">
              <IServer /> Running your own instance?{" "}
              <a href="https://github.com/yasha-dev1/harnext" target="_blank" rel="noreferrer">
                Self-host →
              </a>
            </div>
            <div className="legal">
              By registering you agree to receive occasional updates about Harnext. We
              tag your interest in our mailing list and you can unsubscribe anytime.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
