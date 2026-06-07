import Link from "next/link";

const STATUS_COLORS: Record<string, string> = {
  active: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  success: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  error: "bg-red-500/15 text-red-300 border-red-500/30",
  failed: "bg-red-500/15 text-red-300 border-red-500/30",
  running: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  fast: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  batch: "bg-violet-500/15 text-violet-300 border-violet-500/30",
  update: "bg-neutral-500/15 text-neutral-300 border-neutral-500/30",
};

export function Badge({ value }: { value: string }) {
  const cls = STATUS_COLORS[value] ?? "bg-neutral-500/15 text-neutral-300 border-neutral-500/30";
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}>
      {value}
    </span>
  );
}

export function Card({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40">
      <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-neutral-200">{title}</h2>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  variant = "default",
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "default" | "ghost" | "danger";
  type?: "button" | "submit";
}) {
  const base = "rounded-md px-3 py-1.5 text-sm font-medium transition disabled:opacity-40";
  const styles = {
    default: "bg-neutral-100 text-neutral-900 hover:bg-white",
    ghost: "border border-neutral-700 text-neutral-200 hover:bg-neutral-800",
    danger: "border border-red-700/50 text-red-300 hover:bg-red-950/40",
  }[variant];
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${styles}`}>
      {children}
    </button>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-neutral-400">{label}</span>
      {children}
    </label>
  );
}

export const inputCls =
  "rounded-md border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-100 outline-none focus:border-neutral-500";

export { Link };
