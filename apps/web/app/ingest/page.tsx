"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  CloudUpload,
  Code2,
  Sparkles,
} from "lucide-react";

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
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, PageShell } from "@/components/page-shell";
import { api, ApiError } from "@/lib/api";
import type { HfDataset, HfJobStatus } from "@/lib/types";

type Result = { ok: true; id: string; at: string } | { ok: false; error: string };

const TABS = [
  {
    value: "huggingface",
    label: "HuggingFace",
    icon: Sparkles,
    tagline: "Bulk import a real dataset",
  },
  {
    value: "file",
    label: "File upload",
    icon: CloudUpload,
    tagline: "Drop in a PDF or text file",
  },
  {
    value: "json",
    label: "JSON event",
    icon: Code2,
    tagline: "Hand-craft a CloudEvent",
  },
] as const;

export default function IngestPage() {
  return (
    <PageShell className="max-w-4xl">
      <PageHeader
        title="Ingest"
        description="Pick one of three ways to push something into the pipeline. Events flow through the worker into Graphiti and the FAISS document map."
      />

      <Tabs defaultValue="huggingface" className="w-full">
        <TabsList className="grid w-full grid-cols-3 h-auto p-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <TabsTrigger
                key={t.value}
                value={t.value}
                className="flex-col items-start gap-0.5 py-2 px-3 h-auto data-[state=active]:bg-background"
              >
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <Icon className="h-3.5 w-3.5" />
                  {t.label}
                </span>
                <span className="text-[11px] font-normal text-muted-foreground">
                  {t.tagline}
                </span>
              </TabsTrigger>
            );
          })}
        </TabsList>

        <TabsContent value="huggingface">
          <HuggingFaceImport />
        </TabsContent>
        <TabsContent value="file">
          <FileUpload />
        </TabsContent>
        <TabsContent value="json">
          <JsonEvent />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}

function ResultAlert({ result }: { result: Result | null }) {
  if (!result) return null;
  if (result.ok) {
    return (
      <Alert>
        <CheckCircle2 />
        <AlertTitle>Accepted</AlertTitle>
        <AlertDescription>
          <span className="font-mono text-xs">{result.id}</span>
          <span className="text-muted-foreground"> · {new Date(result.at).toLocaleString()}</span>
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>Error</AlertTitle>
      <AlertDescription>{result.error}</AlertDescription>
    </Alert>
  );
}

function StepNumber({ n }: { n: number }) {
  return (
    <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[11px] font-semibold text-muted-foreground">
      {n}
    </span>
  );
}

function HuggingFaceImport() {
  const [datasets, setDatasets] = useState<HfDataset[]>([]);
  const [dataset, setDataset] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<HfJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api
      .hfDatasets()
      .then((ds) => {
        setDatasets(ds);
        if (ds.length > 0) setDataset(ds[0].key);
      })
      .catch(() => {});
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!dataset) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const r = await api.hfIngest(dataset);
      const initial: HfJobStatus = {
        job_id: r.job_id,
        dataset_id: r.dataset_id,
        dataset_key: r.dataset_key,
        state: "queued",
        target: r.target,
        accepted: 0,
        skipped: 0,
        current_part: null,
        error: null,
        started_at: new Date().toISOString(),
        finished_at: null,
      };
      setJob(initial);
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.hfJob(r.job_id);
          setJob(s);
          if (s.state === "done" || s.state === "failed") {
            stopPolling();
            setBusy(false);
          }
        } catch (err) {
          stopPolling();
          setBusy(false);
          setError(err instanceof Error ? err.message : String(err));
        }
      }, 1500);
    } catch (err) {
      setBusy(false);
      setError(err instanceof ApiError ? `${err.status} ${err.message}` : String(err));
    }
  }

  const selected = datasets.find((d) => d.key === dataset);
  const pct = job
    ? Math.min(100, Math.round(((job.accepted + job.skipped) / Math.max(1, job.target)) * 100))
    : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Import from HuggingFace</CardTitle>
        <CardDescription>
          Pick a supported dataset and ingest it end to end. Each row becomes one CloudEvent,
          embedded, and plotted on the document map.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="hf-dataset" className="flex items-center gap-2">
              <StepNumber n={1} /> Choose a dataset
            </Label>
            <Select value={dataset} onValueChange={setDataset} disabled={busy}>
              <SelectTrigger id="hf-dataset">
                <SelectValue placeholder="Select a dataset" />
              </SelectTrigger>
              <SelectContent>
                {datasets.length === 0 ? (
                  <SelectItem value="__loading" disabled>
                    Loading…
                  </SelectItem>
                ) : (
                  datasets.map((d) => (
                    <SelectItem key={d.key} value={d.key}>
                      {d.label}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {selected && (
              <div className="rounded-md border bg-muted/30 p-3 text-xs space-y-1">
                <div className="font-mono text-[11px] text-muted-foreground">
                  {selected.dataset_id}
                </div>
                <p className="leading-relaxed">{selected.description}</p>
                <p className="text-muted-foreground">
                  ≈ {selected.total_rows.toLocaleString()} rows · ingests the whole dataset
                </p>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 pt-1">
            <Button type="submit" disabled={busy || !dataset}>
              {busy ? "Importing…" : "Start import"}
            </Button>
            {busy && (
              <span className="text-xs text-muted-foreground">
                Polling job every 1.5s — you can leave this tab.
              </span>
            )}
          </div>
        </form>

        {job && (
          <div className="rounded-lg border p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge
                variant={
                  job.state === "failed"
                    ? "destructive"
                    : job.state === "done"
                      ? "success"
                      : "secondary"
                }
              >
                {job.state}
              </Badge>
              <span className="font-mono text-muted-foreground">{job.job_id}</span>
              <span className="ml-auto tabular-nums">
                {job.accepted.toLocaleString()} / ≈ {job.target.toLocaleString()}
                {job.skipped > 0 ? ` (${job.skipped.toLocaleString()} skipped)` : ""}
              </span>
            </div>
            <Progress
              value={pct}
              indicatorClassName={
                job.state === "failed"
                  ? "bg-destructive"
                  : job.state === "done"
                    ? "bg-emerald-500"
                    : "bg-primary"
              }
            />
            {job.current_part && job.state !== "done" && (
              <p className="text-xs text-muted-foreground">
                Current part: <code className="text-[11px]">{job.current_part}</code>
              </p>
            )}
            {job.state === "downloading" && (
              <p className="text-xs text-muted-foreground">
                Fetching from HuggingFace (cached after first run).
              </p>
            )}
            {job.error && (
              <p className="text-xs text-destructive whitespace-pre-wrap">{job.error}</p>
            )}
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

function FileUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await api.ingestFile(file, "file", subject || undefined);
      setResult({ ok: true, id: r.id, at: r.accepted_at });
      setFile(null);
      setSubject("");
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      setResult({ ok: false, error: msg });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload a file</CardTitle>
        <CardDescription>
          PDFs and text files get extracted in the worker. Other types are stored but not parsed in v0.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="file" className="flex items-center gap-2">
              <StepNumber n={1} /> Pick a file
            </Label>
            <label
              htmlFor="file"
              className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed bg-muted/30 px-4 py-6 text-sm hover:bg-muted/50 transition-colors"
            >
              <CloudUpload className="h-5 w-5 text-muted-foreground shrink-0" />
              <div className="min-w-0 flex-1">
                {file ? (
                  <>
                    <div className="font-medium truncate">{file.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {(file.size / 1024).toFixed(1)} KB · {file.type || "unknown type"}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="font-medium">Click to choose a file</div>
                    <div className="text-xs text-muted-foreground">
                      PDF, TXT, MD, or any binary blob
                    </div>
                  </>
                )}
              </div>
            </label>
            <Input
              id="file"
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="sr-only"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="subject" className="flex items-center gap-2">
              <StepNumber n={2} /> Subject{" "}
              <span className="text-xs font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="subject"
              type="text"
              placeholder="defaults to doc:<uuid>"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </div>

          <Button type="submit" disabled={!file || busy}>
            {busy ? "Uploading…" : "Upload"}
          </Button>
        </form>
        <div className="mt-4">
          <ResultAlert result={result} />
        </div>
      </CardContent>
    </Card>
  );
}

function JsonEvent() {
  const [source, setSource] = useState("webhook:demo");
  const [type, setType] = useState("demo.event");
  const [subject, setSubject] = useState("demo:1");
  const [dataText, setDataText] = useState('{\n  "hello": "world"\n}');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      let data: unknown = undefined;
      if (dataText.trim()) {
        try {
          data = JSON.parse(dataText);
        } catch {
          throw new Error("data is not valid JSON");
        }
      }
      const r = await api.ingestJson({ source, type, subject, data });
      setResult({ ok: true, id: r.id, at: r.accepted_at });
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      setResult({ ok: false, error: msg });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Post a JSON event</CardTitle>
        <CardDescription>Construct a CloudEvent envelope and POST it directly.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-5">
          <div className="space-y-2">
            <Label className="flex items-center gap-2">
              <StepNumber n={1} /> Envelope
            </Label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="ev-source" className="text-xs text-muted-foreground">
                  Source
                </Label>
                <Input id="ev-source" value={source} onChange={(e) => setSource(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ev-type" className="text-xs text-muted-foreground">
                  Type
                </Label>
                <Input id="ev-type" value={type} onChange={(e) => setType(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ev-subject" className="text-xs text-muted-foreground">
                  Subject
                </Label>
                <Input
                  id="ev-subject"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="ev-data" className="flex items-center gap-2">
              <StepNumber n={2} /> Data (JSON)
            </Label>
            <Textarea
              id="ev-data"
              value={dataText}
              onChange={(e) => setDataText(e.target.value)}
              rows={8}
              className="font-mono text-xs"
            />
          </div>

          <Button type="submit" disabled={busy}>
            {busy ? "Posting…" : "Post event"}
          </Button>
        </form>
        <div className="mt-4">
          <ResultAlert result={result} />
        </div>
      </CardContent>
    </Card>
  );
}
