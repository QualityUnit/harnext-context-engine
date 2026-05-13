"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Search, User } from "lucide-react";

import { Input } from "@/components/ui/input";
import { ModeToggle } from "@/components/mode-toggle";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";

const LABELS: Record<string, string> = {
  "": "Overview",
  events: "Events",
  graph: "Graph",
  documents: "Documents",
  ingest: "Ingest",
};

function useCrumbs(pathname: string | null) {
  if (!pathname) return [{ label: "Overview", href: "/" }];
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return [{ label: "Overview", href: "/" }];
  const crumbs = [{ label: "meaninggrid", href: "/" }];
  let acc = "";
  for (const part of parts) {
    acc += "/" + part;
    crumbs.push({ label: LABELS[part] ?? decodeURIComponent(part), href: acc });
  }
  return crumbs;
}

export function AppTopbar() {
  const pathname = usePathname();
  const crumbs = useCrumbs(pathname);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 px-4 md:px-6">
      <nav className="flex items-center gap-1 text-sm min-w-0">
        {crumbs.map((c, i) => (
          <React.Fragment key={c.href}>
            {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60" />}
            <Link
              href={c.href}
              className={
                i === crumbs.length - 1
                  ? "font-medium truncate"
                  : "text-muted-foreground hover:text-foreground truncate"
              }
            >
              {c.label}
            </Link>
          </React.Fragment>
        ))}
      </nav>

      <div className="flex-1" />

      <div className="relative hidden lg:block w-72">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          type="search"
          placeholder="Search events, entities, docs…"
          className="pl-8 h-9"
        />
      </div>

      <ModeToggle />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="User menu">
            <User className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel>Tenant</DropdownMenuLabel>
          <DropdownMenuItem disabled className="font-mono text-xs">
            default
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem>Profile</DropdownMenuItem>
          <DropdownMenuItem>Settings</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
