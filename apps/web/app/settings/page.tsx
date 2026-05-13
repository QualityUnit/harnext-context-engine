"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, PageShell } from "@/components/page-shell";
import { api, ApiError } from "@/lib/api";
import type { ResetSummary } from "@/lib/types";

const CONFIRM_PHRASE = "RESET";

export default function SettingsPage() {
  return (
    <PageShell className="max-w-3xl">
      <PageHeader
        title="Settings"
        description="Configuration and admin controls. v0 ships with one panel."
      />
      <DangerZone />
    </PageShell>
  );
}

function DangerZone() {
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ResetSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canReset = confirm === CONFIRM_PHRASE && !busy;

  async function doReset() {
    if (!canReset) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.adminReset(CONFIRM_PHRASE);
      setResult(r);
      setConfirm("");
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-destructive" />
          <CardTitle className="text-destructive">Danger zone</CardTitle>
        </div>
        <CardDescription>
          Destructive, immediate, irrecoverable. Touches every store the platform owns.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2 text-sm">
          <div className="font-medium">Reset all data</div>
          <p className="text-muted-foreground">Wipes every piece of state, then reseeds the default tenant:</p>
          <ul className="text-xs text-muted-foreground space-y-1 pl-4 list-disc">
            <li>Every <code>:Entity</code> / <code>:Episodic</code> node + edge in FalkorDB (all tenants)</li>
            <li>All rows in <code>ingested_events</code>, <code>sink_outcomes</code>, <code>vector_documents</code>; <code>tenants</code> reseeded</li>
            <li>Every object in the MinIO blob bucket</li>
            <li>Every per-tenant FAISS index file in <code>data/faiss/</code></li>
            <li>The Kafka topics <code>events.raw.v1</code> + DLQs (Redpanda re-creates them on next publish)</li>
          </ul>
        </div>

        <Alert variant="destructive" className="border-destructive/40">
          <AlertTriangle />
          <AlertTitle>This cannot be undone</AlertTitle>
          <AlertDescription>
            After the reset succeeds, restart the worker (<code>make worker</code>) — its Kafka consumer loop will be in an undefined state once <code>events.raw.v1</code> is dropped.
          </AlertDescription>
        </Alert>

        <div className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
          <Label htmlFor="confirm" className="text-sm">
            Type <code className="rounded bg-background px-1 py-0.5 text-destructive">{CONFIRM_PHRASE}</code> to enable the button
          </Label>
          <Input
            id="confirm"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder={CONFIRM_PHRASE}
            disabled={busy}
            className="font-mono"
            autoComplete="off"
            spellCheck={false}
          />
          <div className="flex items-center gap-3 pt-1">
            <Button
              type="button"
              variant="destructive"
              disabled={!canReset}
              onClick={doReset}
            >
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Wiping…
                </>
              ) : (
                "Reset all data"
              )}
            </Button>
            {busy && (
              <span className="text-xs text-muted-foreground">
                Dropping FalkorDB graphs, emptying MinIO, deleting Kafka topics…
              </span>
            )}
          </div>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertTitle>Reset failed</AlertTitle>
            <AlertDescription className="whitespace-pre-wrap">{error}</AlertDescription>
          </Alert>
        )}

        {result && <ResetResultDisplay r={result} />}
      </CardContent>
    </Card>
  );
}

function ResetResultDisplay({ r }: { r: ResetSummary }) {
  const rowsBefore = Object.entries(r.sqlite_rows_before);
  const totalRows = rowsBefore.reduce((acc, [, n]) => acc + n, 0);

  return (
    <Alert className="border-emerald-500/40 bg-emerald-500/5">
      <CheckCircle2 className="text-emerald-500" />
      <AlertTitle className="text-emerald-700 dark:text-emerald-400">
        Reset complete
      </AlertTitle>
      <AlertDescription>
        <div className="mt-2 space-y-3 text-xs">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="FalkorDB graphs" value={r.falkordb_graphs.length} />
            <Stat label="SQLite rows" value={totalRows} />
            <Stat label="MinIO objects" value={r.minio_objects} />
            <Stat label="FAISS files" value={r.faiss_files} />
            <Stat label="Kafka topics" value={r.kafka_topics.length} />
            <Stat label="Tenants reseeded" value={r.tenants_reseeded.length} />
          </div>

          {rowsBefore.length > 0 && (
            <div>
              <div className="font-medium text-foreground mb-1">SQLite before wipe</div>
              <div className="flex flex-wrap gap-1">
                {rowsBefore.map(([table, n]) => (
                  <Badge key={table} variant="secondary" className="font-mono text-[10px]">
                    {table}: {n.toLocaleString()}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {r.kafka_topics.length > 0 && (
            <div>
              <div className="font-medium text-foreground mb-1">Kafka topics deleted</div>
              <div className="flex flex-wrap gap-1">
                {r.kafka_topics.map((t) => (
                  <Badge key={t} variant="secondary" className="font-mono text-[10px]">
                    {t}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {r.notes.length > 0 && (
            <div>
              <div className="font-medium text-foreground mb-1">Notes</div>
              <ul className="space-y-1 pl-4 list-disc text-muted-foreground">
                {r.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </AlertDescription>
    </Alert>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border bg-background p-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="text-lg font-semibold tabular-nums">{value.toLocaleString()}</div>
    </div>
  );
}
