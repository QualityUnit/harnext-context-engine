"use client";

import { useEffect, useRef, useState } from "react";
import type { User } from "@/lib/api";
import type { Ws } from "@/lib/workspace";
import { Icon } from "@/components/DashIcons";

export type View = "sources" | "connect" | "settings";

function WorkspaceSwitcher({
  workspaces,
  current,
  onSwitch,
  onCreate,
}: {
  workspaces: Ws[];
  current: Ws;
  onSwitch: (id: string) => void;
  onCreate: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  return (
    <div className="ws" ref={ref}>
      <button className="ws-btn" onClick={() => setOpen((o) => !o)}>
        <span
          className="ws-mark"
          style={{ background: current.color + "22", color: current.color, borderColor: current.color + "55" }}
        >
          {current.mark}
        </span>
        <span className="ws-meta">
          <span className="ws-name">{current.name}</span>
          <span className="ws-kind">{current.kind}</span>
        </span>
        <span className="ws-chev">
          <Icon.chevron size={15} />
        </span>
      </button>
      {open && (
        <div className="ws-pop">
          <div className="ws-pop-label">Projects</div>
          {workspaces.map((w) => (
            <button
              key={w.id}
              className={"ws-item" + (w.id === current.id ? " active" : "")}
              onClick={() => {
                onSwitch(w.id);
                setOpen(false);
              }}
            >
              <span
                className="ws-mark sm"
                style={{ background: w.color + "22", color: w.color, borderColor: w.color + "55" }}
              >
                {w.mark}
              </span>
              <span className="ws-item-meta">
                <span className="ws-name">{w.name}</span>
                <span className="ws-kind">{w.kind}</span>
              </span>
              {w.id === current.id && (
                <span className="ws-tick">
                  <Icon.check size={14} />
                </span>
              )}
            </button>
          ))}
          <div className="ws-pop-div" />
          <button
            className="ws-item create"
            onClick={() => {
              onCreate();
              setOpen(false);
            }}
          >
            <span className="ws-mark sm new">
              <Icon.plus size={15} />
            </span>
            <span className="ws-name">New project</span>
          </button>
        </div>
      )}
    </div>
  );
}

export function Sidebar({
  workspaces,
  current,
  view,
  user,
  onView,
  onSwitch,
  onCreate,
  onLogout,
}: {
  workspaces: Ws[];
  current: Ws;
  view: View;
  user: User | null;
  onView: (v: View) => void;
  onSwitch: (id: string) => void;
  onCreate: () => void;
  onLogout: () => void;
}) {
  const nav = [
    { id: "sources" as const, label: "Sources", icon: Icon.sources },
    { id: "connect" as const, label: "Connect", icon: Icon.connect },
  ];
  const label = user?.name || user?.email || "self-hosted";
  const initials = (user?.name || user?.email || "MG")
    .split(/[\s@.]+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <span className="brand-grid" />
        </span>
        <span className="brand-name">MeaningGrid</span>
        <span className="brand-badge">OSS</span>
      </div>

      <WorkspaceSwitcher workspaces={workspaces} current={current} onSwitch={onSwitch} onCreate={onCreate} />

      <nav className="nav">
        {nav.map((n) => (
          <button
            key={n.id}
            className={"nav-item" + (view === n.id ? " active" : "")}
            onClick={() => onView(n.id)}
          >
            <n.icon size={17} />
            <span>{n.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-foot">
        <button
          className={"nav-item" + (view === "settings" ? " active" : "")}
          onClick={() => onView("settings")}
        >
          <Icon.settings size={17} />
          <span>Settings</span>
        </button>
        <div className="user">
          <span className="user-av">
            {user?.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
            ) : (
              initials
            )}
          </span>
          <span className="user-meta">
            <span className="user-name">{label}</span>
            <span className="user-plan">Self-hosted</span>
          </span>
          <button className="user-logout" title="Log out" onClick={onLogout}>
            <Icon.logout size={15} />
          </button>
        </div>
      </div>
    </aside>
  );
}
