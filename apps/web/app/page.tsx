"use client";

import Link from "next/link";
import useSWR from "swr";
import {
  Activity,
  ArrowUpRight,
  Database,
  Inbox,
  Layers,
  Network,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, PageShell } from "@/components/page-shell";
import { fetcher } from "@/lib/api";
import type { EventSummary } from "@/lib/types";

function startOfToday() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function formatRelative(iso: string) {
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export default function Home() {
  const { data, isLoading } = useSWR<EventSummary[]>(
    "/api/v1/events?limit=100",
    fetcher,
    { refreshInterval: 5000 },
  );

  const events = data ?? [];
  const today = events.filter((e) => new Date(e.ingest_time).getTime() >= startOfToday()).length;
  const sources = new Set(events.map((e) => e.source)).size;
  const withBlob = events.filter((e) => e.has_blob).length;

  const stats = [
    {
      label: "Events (window)",
      value: events.length,
      hint: "last 100 ingested",
      icon: Activity,
    },
    {
      label: "Today",
      value: today,
      hint: "since 00:00 local",
      icon: Layers,
    },
    {
      label: "Sources",
      value: sources,
      hint: "distinct in window",
      icon: Network,
    },
    {
      label: "With blob",
      value: withBlob,
      hint: "carry a payload",
      icon: Database,
    },
  ];

  return (
    <PageShell>
      <PageHeader
        title="Overview"
        description="What the pipeline has ingested and how the semantic layer is doing."
        actions={
          <Button asChild size="sm">
            <Link href="/ingest">
              <Inbox /> Ingest
            </Link>
          </Button>
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <Card key={s.label}>
              <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
                <CardDescription className="text-xs uppercase tracking-wider">
                  {s.label}
                </CardDescription>
                <Icon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <Skeleton className="h-8 w-16" />
                ) : (
                  <div className="text-2xl font-semibold tabular-nums">{s.value}</div>
                )}
                <p className="text-xs text-muted-foreground mt-1">{s.hint}</p>
              </CardContent>
            </Card>
          );
        })}
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card className="overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle>Recent events</CardTitle>
              <CardDescription>The freshest items the worker has processed.</CardDescription>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href="/events">
                View all <ArrowUpRight />
              </Link>
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {isLoading && (
              <div className="px-6 py-4 space-y-2">
                <Skeleton className="h-5 w-full" />
                <Skeleton className="h-5 w-4/5" />
                <Skeleton className="h-5 w-3/5" />
              </div>
            )}
            {!isLoading && events.length === 0 && (
              <div className="px-6 py-10 text-center text-sm text-muted-foreground">
                No events yet. Try <Link href="/ingest" className="underline">/ingest</Link>.
              </div>
            )}
            {!isLoading && events.length > 0 && (
              <ul className="divide-y">
                {events.slice(0, 8).map((e) => (
                  <li key={e.id}>
                    <Link
                      href={`/events/${encodeURIComponent(e.id)}`}
                      className="flex items-center gap-3 px-6 py-2.5 hover:bg-muted/50 transition-colors text-sm"
                    >
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {e.source}
                      </Badge>
                      <span className="truncate flex-1 min-w-0">{e.subject}</span>
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatRelative(e.ingest_time)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Jump in</CardTitle>
            <CardDescription>Explore the pipeline.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <NavCard
              href="/graph"
              icon={Network}
              title="Semantic graph"
              body="Entities and facts Graphiti built from your events."
            />
            <NavCard
              href="/documents"
              icon={Database}
              title="Document map"
              body="2D embedding projection of every ingested doc."
            />
            <NavCard
              href="/ingest"
              icon={Inbox}
              title="Ingest"
              body="Upload, post JSON, or import from HuggingFace."
            />
          </CardContent>
        </Card>
      </section>
    </PageShell>
  );
}

function NavCard({
  href,
  icon: Icon,
  title,
  body,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  body: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-start gap-3 rounded-md border p-3 hover:bg-muted/50 transition-colors group"
    >
      <div className="mt-0.5 rounded-md bg-muted p-2 group-hover:bg-background transition-colors">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{title}</div>
        <div className="text-xs text-muted-foreground line-clamp-2">{body}</div>
      </div>
      <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground/60 mt-1" />
    </Link>
  );
}
