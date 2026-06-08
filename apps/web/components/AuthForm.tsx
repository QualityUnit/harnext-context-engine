"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { API_BASE, api } from "@/lib/api";
import { setSession } from "@/lib/auth";
import {
  IAlert,
  IArrow,
  ICheck,
  IEye,
  IEyeOff,
  IGitHub,
  IGoogle,
  ILock,
  IMail,
  IServer,
  IUser,
} from "@/components/Icons";

const ERROR_MESSAGES: Record<string, string> = {
  google_not_configured: "Google sign-in isn’t configured on this instance — use email or GitHub.",
  github_not_configured: "GitHub sign-in isn’t configured on this instance — use email or Google.",
  github_no_email: "Couldn’t read your GitHub email. Make it public, or use another method.",
  auth_failed: "Sign-in failed. Please try again.",
  no_token: "Sign-in failed. Please try again.",
};

function Field({
  icon,
  type = "text",
  label,
  labelAside,
  value,
  onChange,
  placeholder,
  err,
  autoFocus,
}: {
  icon: React.ReactNode;
  type?: string;
  label: string;
  labelAside?: React.ReactNode;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  err?: string | null;
  autoFocus?: boolean;
}) {
  const [show, setShow] = useState(false);
  const isPw = type === "password";
  return (
    <div>
      <div className="field-label">
        <span>{label}</span>
        {labelAside}
      </div>
      <div className={"field" + (err ? " bad" : "")}>
        <span className="field-ic">{icon}</span>
        <input
          type={isPw && show ? "text" : type}
          value={value}
          autoFocus={autoFocus}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
        {isPw && (
          <button type="button" className="field-eye" onClick={() => setShow((s) => !s)} aria-label="Toggle password">
            {show ? <IEyeOff /> : <IEye />}
          </button>
        )}
      </div>
      {err && (
        <div className="field-err">
          <IAlert />
          {err}
        </div>
      )}
    </div>
  );
}

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const search = useSearchParams();
  const [f, setF] = useState({ name: "", email: "", pw: "" });
  const [errs, setErrs] = useState<Record<string, string | null>>({});
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");
  const [formError, setFormError] = useState<string | null>(null);

  const [oauth, setOauth] = useState<{ github: boolean; google: boolean } | null>(null);
  useEffect(() => {
    api
      .health()
      .then((h) => setOauth({ github: h.oauth.github, google: h.oauth.google }))
      .catch(() => setOauth({ github: false, google: false }));
  }, []);

  const isSignup = mode === "signup";
  const set = (k: keyof typeof f) => (v: string) => {
    setF((p) => ({ ...p, [k]: v }));
    setErrs((e) => ({ ...e, [k]: null }));
    setFormError(null);
  };

  const qError = search.get("error");
  const queryMsg = qError ? (ERROR_MESSAGES[qError] ?? `Sign-in error: ${qError}`) : null;

  async function submit() {
    const e: Record<string, string> = {};
    if (isSignup && f.name.trim().length < 2) e.name = "Enter your name";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email)) e.email = "Enter a valid email";
    if (f.pw.length < 8) e.pw = "At least 8 characters";
    setErrs(e);
    if (Object.keys(e).length) return;

    setState("loading");
    setFormError(null);
    try {
      const out = isSignup
        ? await api.register(f.email.trim(), f.pw, f.name.trim())
        : await api.login(f.email.trim(), f.pw);
      setSession(out.token, out.user);
      setState("done");
    } catch (err) {
      const msg = String(err);
      setState("idle");
      setFormError(
        isSignup
          ? msg.includes("409")
            ? "That email is already registered. Sign in instead."
            : "Couldn’t create account. Check your details and try again."
          : "Invalid email or password.",
      );
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
            MeaningGrid<span className="fc-oss">OSS</span>
          </div>
        </div>

        {state === "done" ? (
          <div className="success">
            <div className="succ-ic">
              <ICheck />
            </div>
            <div className="succ-title">{isSignup ? "Account created" : "Welcome back"}</div>
            <div className="succ-sub">
              {isSignup
                ? "Your workspace is ready to fill with context."
                : "Spinning up your workspace…"}
            </div>
            <a className="succ-btn" href="/projects">
              Open dashboard <IArrow />
            </a>
          </div>
        ) : (
          <>
            <div className="fc-head">
              <div className="fc-title">{isSignup ? "Create your account" : "Sign in to MeaningGrid"}</div>
              <div className="fc-sub">
                {isSignup
                  ? "Start indexing context in under a minute."
                  : "Welcome back. Pick up where your agents left off."}
              </div>
            </div>

            {oauth && (oauth.github || oauth.google) && (
              <>
                <div className="oauth">
                  {oauth.github && (
                    <a className="oauth-btn gh" href={`${API_BASE}/auth/github/start`}>
                      <IGitHub />
                      Continue with GitHub
                    </a>
                  )}
                  {oauth.google && (
                    <a className="oauth-btn" href={`${API_BASE}/auth/google/start`}>
                      <IGoogle />
                      Continue with Google
                    </a>
                  )}
                </div>
                <div className="divider">or {isSignup ? "sign up" : "sign in"} with email</div>
              </>
            )}

            <div className="field-group">
              {isSignup && (
                <Field icon={<IUser />} label="Name" value={f.name} onChange={set("name")} placeholder="Ada Lovelace" err={errs.name} autoFocus />
              )}
              <Field
                icon={<IMail />}
                type="email"
                label="Email"
                value={f.email}
                onChange={set("email")}
                placeholder="dev@acme.io"
                err={errs.email}
                autoFocus={!isSignup}
              />
              <Field
                icon={<ILock />}
                type="password"
                label="Password"
                labelAside={!isSignup ? <a href="#">Forgot?</a> : undefined}
                value={f.pw}
                onChange={set("pw")}
                placeholder={isSignup ? "8+ characters" : "••••••••"}
                err={errs.pw}
              />
            </div>

            {(formError || queryMsg) && (
              <div className="field-err" style={{ justifyContent: "center", marginTop: 14 }}>
                <IAlert />
                {formError ?? queryMsg}
              </div>
            )}

            <button className="submit" onClick={submit} disabled={state === "loading"}>
              {state === "loading" ? (
                <span className="spin" />
              ) : (
                <>
                  {isSignup ? "Create account" : "Sign in"}
                  <IArrow />
                </>
              )}
            </button>

            <div className="toggle">
              {isSignup ? (
                <>
                  Already have an account?{" "}
                  <button onClick={() => router.push("/login")}>Sign in</button>
                </>
              ) : (
                <span style={{ color: "var(--tx-3)" }}>
                  Invite-only — ask an admin to create your account.
                </span>
              )}
            </div>

            <div className="selfhost">
              <IServer /> Running your own instance?{" "}
              <a href="https://github.com/" target="_blank" rel="noreferrer">
                Self-host →
              </a>
            </div>
            {isSignup && (
              <div className="legal">
                By continuing you agree to our <a href="#">Terms</a> &amp; <a href="#">Privacy Policy</a>.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
