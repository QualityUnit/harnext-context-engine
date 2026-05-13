"use client";

import Link from "next/link";
import useSWR from "swr";
import { AlertCircle, FileText, Inbox, RefreshCw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader, PageShell } from "@/components/page-shell";
import { fetcher } from "@/lib/api";
import type { EventSummary } from "@/lib/types";

export default function EventsPage() {
  const { data, error, isLoading, mutate, isValidating } = useSWR<EventSummary[]>(
    "/api/v1/events?limit=100",
    fetcher,
    { refreshInterval: 5000 },
  );

  return (
    <PageShell>
      <PageHeader
        title="Events"
        description="Every CloudEvent the ingest endpoint has accepted, freshest first."
        actions={
          <>
            <Badge variant="secondary" className="font-normal">
              auto-refresh 5s
            </Badge>
            <Button
              variant="outline"
              size="sm"
              onClick={() => mutate()}
              disabled={isValidating}
            >
              <RefreshCw className={isValidating ? "animate-spin" : undefined} />
              Refresh
            </Button>
          </>
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertTitle>Failed to load events</AlertTitle>
          <AlertDescription>{String(error.message ?? error)}</AlertDescription>
        </Alert>
      )}

      {!error && (
      <Card>
        <CardContent className="p-0">
          {isLoading && (
            <div className="p-6 space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-7 w-full" />
              ))}
            </div>
          )}

          {!isLoading && data && data.length === 0 && (
            <div className="px-6 py-16 text-center space-y-3">
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-muted">
                <Inbox className="h-5 w-5 text-muted-foreground" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">No events yet</p>
                <p className="text-xs text-muted-foreground">
                  Try <Link href="/ingest" className="underline">/ingest</Link> to add one.
                </p>
              </div>
              <Button asChild size="sm">
                <Link href="/ingest">Open Ingest</Link>
              </Button>
            </div>
          )}

          {!isLoading && data && data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[160px]">Ingested</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Subject</TableHead>
                  <TableHead className="w-[60px]">Blob</TableHead>
                  <TableHead>Id</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {new Date(e.ingest_time).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {e.source}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{e.type}</TableCell>
                    <TableCell className="max-w-[280px] truncate">{e.subject}</TableCell>
                    <TableCell>
                      {e.has_blob ? (
                        <FileText className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/events/${encodeURIComponent(e.id)}`}
                        className="font-mono text-xs text-muted-foreground hover:text-foreground hover:underline"
                      >
                        {e.id.length > 36 ? e.id.slice(0, 36) + "…" : e.id}
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      )}
    </PageShell>
  );
}
