"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Home" },
  { href: "/events", label: "Events" },
  { href: "/graph", label: "Graph" },
  { href: "/ingest", label: "Ingest" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="border-b border-black/10 dark:border-white/10">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-6">
        <Link href="/" className="font-semibold tracking-tight">meaninggrid</Link>
        <div className="flex gap-4 text-sm">
          {links.slice(1).map((l) => {
            const active = pathname === l.href || pathname?.startsWith(l.href + "/");
            return (
              <Link
                key={l.href}
                href={l.href}
                className={
                  active
                    ? "underline underline-offset-4"
                    : "opacity-70 hover:opacity-100"
                }
              >
                {l.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
