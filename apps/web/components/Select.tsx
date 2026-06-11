"use client";

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Icon } from "@/components/DashIcons";

export type SelectOption = {
  value: string;
  label: string;
  /** Optional secondary line shown under the label. */
  hint?: string;
};

type PopPos = { left: number; top: number; width: number; maxHeight: number; up: boolean };

/**
 * Custom dropdown that matches the Harnext design system (see `.sel*` in
 * globals.css). Drop-in replacement for a native <select>: controlled via
 * `value` / `onChange`, with keyboard nav, click-outside, and a placeholder.
 *
 * The list is rendered in a portal with fixed positioning so it is never
 * clipped by an ancestor's `overflow: hidden` (e.g. the add-source modal), and
 * it flips above the trigger when there isn't room below.
 */
export function Select({
  value,
  onChange,
  options,
  placeholder = "Select…",
  icon,
  disabled = false,
  loading = false,
  emptyText = "No options",
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  icon?: ReactNode;
  disabled?: boolean;
  loading?: boolean;
  emptyText?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1); // keyboard-highlighted index
  const [pos, setPos] = useState<PopPos | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const selected = options.find((o) => o.value === value) ?? null;
  const isDisabled = disabled || loading;

  // Position the popup relative to the trigger, clamped/flipped to the viewport.
  const reposition = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    const gap = 6;
    const margin = 8;
    const below = window.innerHeight - r.bottom - gap - margin;
    const above = r.top - gap - margin;
    const up = below < 200 && above > below;
    setPos({
      left: r.left,
      top: up ? r.top - gap : r.bottom + gap,
      width: r.width,
      maxHeight: Math.min(280, Math.max(120, up ? above : below)),
      up,
    });
  }, []);

  // Close when clicking outside both the trigger and the (portaled) popup.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || popRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Reposition while open on scroll / resize.
  useLayoutEffect(() => {
    if (!open) return;
    reposition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, reposition]);

  // On open, highlight the selected option (or the first one).
  useEffect(() => {
    if (!open) return;
    const i = options.findIndex((o) => o.value === value);
    setActive(i >= 0 ? i : 0);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the highlighted option scrolled into view.
  useEffect(() => {
    if (!open || active < 0) return;
    const el = popRef.current?.children[active] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const choose = useCallback(
    (v: string) => {
      onChange(v);
      setOpen(false);
    },
    [onChange]
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (isDisabled) return;
    if (!open) {
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }
    switch (e.key) {
      case "Escape":
        e.preventDefault();
        setOpen(false);
        break;
      case "ArrowDown":
        e.preventDefault();
        setActive((i) => Math.min(options.length - 1, i + 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActive((i) => Math.max(0, i - 1));
        break;
      case "Home":
        e.preventDefault();
        setActive(0);
        break;
      case "End":
        e.preventDefault();
        setActive(options.length - 1);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        if (active >= 0 && active < options.length) choose(options[active].value);
        break;
      case "Tab":
        setOpen(false);
        break;
    }
  };

  return (
    <div className={"sel" + (isDisabled ? " disabled" : "")}>
      <button
        ref={btnRef}
        type="button"
        className={"sel-btn" + (open ? " open" : "")}
        onClick={() => !isDisabled && setOpen((o) => !o)}
        onKeyDown={onKeyDown}
        disabled={isDisabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={ariaLabel}
      >
        {icon && <span className="sel-ic">{icon}</span>}
        <span className={"sel-val" + (selected ? "" : " ph")}>
          {loading ? "Loading…" : selected ? selected.label : placeholder}
        </span>
        <span className={"sel-chev" + (open ? " up" : "")}>
          <Icon.chevron size={15} />
        </span>
      </button>
      {open &&
        pos &&
        createPortal(
          <div
            ref={popRef}
            id={listId}
            role="listbox"
            aria-label={ariaLabel}
            className={"sel-pop" + (pos.up ? " up" : "")}
            style={{
              left: pos.left,
              top: pos.top,
              width: pos.width,
              maxHeight: pos.maxHeight,
              transform: pos.up ? "translateY(-100%)" : undefined,
            }}
          >
            {options.length === 0 ? (
              <div className="sel-empty">{emptyText}</div>
            ) : (
              options.map((o, i) => (
                <button
                  type="button"
                  key={o.value}
                  role="option"
                  aria-selected={o.value === value}
                  className={
                    "sel-opt" + (o.value === value ? " active" : "") + (i === active ? " hi" : "")
                  }
                  onClick={() => choose(o.value)}
                  onMouseEnter={() => setActive(i)}
                >
                  <span className="sel-opt-text">
                    <span className="sel-opt-name">{o.label}</span>
                    {o.hint && <span className="sel-opt-hint">{o.hint}</span>}
                  </span>
                  {o.value === value && (
                    <span className="sel-tick">
                      <Icon.check size={14} />
                    </span>
                  )}
                </button>
              ))
            )}
          </div>,
          document.body
        )}
    </div>
  );
}
