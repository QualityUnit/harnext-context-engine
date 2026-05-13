"use client";

import { use } from "react";
import useSWR from "swr";
import { AlertCircle, ArrowLeft, CheckCircle2, Clock, XCircle } from "lucide-react";
import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import type { EventDetail, SinkStatus } from "@/lib/types";

function statusBadge(status: SinkStatus["status"]) {
  switch (status) {
    case "success":
      return (
        <Badge variant="success" className="gap-1">
          <CheckCircle2 className="h-3 w-3" /> success
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive" className="gap-1">
          <XCircle className="h-3 w-3" /> failed
        </Badge>
      );
    case "pending":
      return (
        <Badge variant="warning" className="gap-1">
          <Clock className="h-3 w-3" /> pending
        </Badge>
      );
    default:
      return <Badge variant="secondary">{status}</Badge>;
  }
}

export default function EventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const decoded = decodeURIComponent(id);
  const { data, error, isLoading } = useSWR<EventDetail>(
    `/api/v1/events/${encodeURIComponent(decoded)}`,
    fetcher,
    { refreshInterval: 3000 },
  );

  return (
    <PageShell>
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href="/events">
            <ArrowLeft /> Events
          </Link>
        </Button>
        <PageHeader
          title={<span className="font-mono text-base sm:text-lg break-all">{decoded}</span>}
          description={
            data ? (
              <span className="flex flex-wrap gap-1.5">
                <Badge variant="outline" className="font-mono text-[10px]">{data.source}</Badge>
                <Badge variant="outline" className="font-mono text-[10px]">{data.type}</Badge>
                <Badge variant="outline" className="font-mono text-[10px]">{data.subject}</Badge>
              </span>
            ) : null
          }
        />
      </div>

      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertTitle>Failed to load event</AlertTitle>
          <AlertDescription>{String(error.message ?? error)}</AlertDescription>
        </Alert>
      )}

      {data && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Sink status</CardTitle>
              <CardDescription>
                Per-sink processing state from the worker.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {data.sinks.length === 0 ? (
                <div className="px-6 pb-6 text-sm text-muted-foreground">
                  No sink outcomes recorded yet — the worker may not have processed this event.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Sink</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="w-[100px]">Attempts</TableHead>
                      <TableHead>Completed</TableHead>
                      <TableHead>Error</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.sinks.map((s) => (
                      <TableRow key={s.sink}>
                        <TableCell className="font-mono text-xs">{s.sink}</TableCell>
                        <TableCell>{statusBadge(s.status)}</TableCell>
                        <TableCell className="tabular-nums">{s.attempts}</TableCell>
                        <TableCell className="text-muted-foreground whitespace-nowrap">
                          {s.completed_at ? new Date(s.completed_at).toLocaleString() : "—"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground max-w-md truncate">
                          {s.last_error ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Envelope</CardTitle>
              <CardDescription>Raw CloudEvent JSON.</CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="text-xs bg-muted rounded-md p-4 overflow-auto max-h-[480px]">
                {JSON.stringify(JSON.parse(data.envelope_json), null, 2)}
              </pre>
            </CardContent>
          </Card>
        </>
      )}
    </PageShell>
  );
}
