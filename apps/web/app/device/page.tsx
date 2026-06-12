"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher, type DeviceLookup, type Project } from "@/lib/api";
import { useUser } from "@/lib/auth";

// Standalone page a harness opens (verification_uri) so the user can approve its
// device-flow request against one of their projects. The CLI shows a user_code;
// the link prefills it via ?code=.
function DeviceApproval() {
  const params = useSearchParams();
  const user = useUser(false);
  const [code, setCode] = useState("");
  const [lookup, setLookup] = useState<DeviceLookup | null>(null);
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<"approved" | "denied" | null>(null);
  const [busy, setBusy] = useState(false);

  const projects = useSWR<Project[]>(user ? "/projects" : null, fetcher);

  useEffect(() => {
    const c = params.get("code");
    if (c) setCode(c.toUpperCase());
  }, [params]);

  // Resolve the code (auto once prefilled + logged in) so we can show the client.
  async function resolve(c: string) {
    setError(null);
    try {
      setLookup(await api.deviceLookup(c.trim()));
    } catch {
      setLookup(null);
      setError("That code wasn’t found or has expired. Check the code shown in your terminal.");
    }
  }

  useEffect(() => {
    if (user && code && !lookup) void resolve(code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, code]);

  useEffect(() => {
    if (projects.data && projects.data.length && !projectId) setProjectId(projects.data[0].id);
  }, [projects.data, projectId]);

  async function approve() {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      await api.approveDevice(lookup!.user_code, projectId);
      setDone("approved");
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, "") || "Approval failed.");
    } finally {
      setBusy(false);
    }
  }

  async function deny() {
    setBusy(true);
    try {
      await api.denyDevice(lookup!.user_code);
      setDone("denied");
    } catch {
      /* best-effort */
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="page-grid" aria-hidden="true" />
      <div className="form-card">
        <div className="fc-brand">
          <span className="fc-emblem-mark">
            <span className="brand-grid" />
          </span>
          <div className="fc-wordmark">
            Harnext<span className="fc-oss">OSS</span>
          </div>
        </div>

        {done ? (
          <div className="success">
            <div className="succ-title">
              {done === "approved" ? "Harness connected" : "Request denied"}
            </div>
            <div className="succ-sub">
              {done === "approved"
                ? "You can return to your terminal — your harness now pushes conversations to this project."
                : "The device request was denied. Nothing was connected."}
            </div>
            <a className="succ-btn" href="/projects">
              Open dashboard
            </a>
          </div>
        ) : !user ? (
          <div className="success">
            <div className="succ-title">Sign in to approve</div>
            <div className="succ-sub">
              Log in to your Harnext account, then re-open the link shown in your terminal.
            </div>
            <a className="succ-btn" href="/login">
              Sign in
            </a>
          </div>
        ) : (
          <>
            <div className="fc-head">
              <div className="fc-title">Connect a harness</div>
              <div className="fc-sub">
                A command-line harness wants to push its conversations to one of your projects.
                Confirm the code and choose where it lands.
              </div>
            </div>

            <div className="field-group">
              <div>
                <div className="field-label">
                  <span>Device code</span>
                </div>
                <div className="field">
                  <input
                    value={code}
                    onChange={(e) => setCode(e.target.value.toUpperCase())}
                    onBlur={() => code && resolve(code)}
                    placeholder="XXXX-XXXX"
                    autoFocus
                  />
                </div>
              </div>

              {lookup && (
                <div>
                  <div className="field-label">
                    <span>Requesting client</span>
                  </div>
                  <div className="field" style={{ pointerEvents: "none" }}>
                    <input value={lookup.client_id} readOnly />
                  </div>
                </div>
              )}

              {lookup && (
                <div>
                  <div className="field-label">
                    <span>Grant access to project</span>
                  </div>
                  <div className="field">
                    <select
                      value={projectId}
                      onChange={(e) => setProjectId(e.target.value)}
                      style={{ flex: 1, background: "transparent", border: 0, outline: 0, color: "inherit" }}
                    >
                      {(projects.data ?? []).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}
            </div>

            {error && (
              <div className="field-err" style={{ justifyContent: "center", marginTop: 14 }}>
                {error}
              </div>
            )}

            <button
              className="submit"
              onClick={approve}
              disabled={busy || !lookup || !projectId || lookup.status !== "pending"}
            >
              {lookup && lookup.status !== "pending" ? "Code already used" : "Approve"}
            </button>
            {lookup && lookup.status === "pending" && (
              <button
                className="toggle"
                onClick={deny}
                disabled={busy}
                style={{ marginTop: 10, width: "100%" }}
              >
                Deny this request
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function DevicePage() {
  return (
    <Suspense>
      <DeviceApproval />
    </Suspense>
  );
}
