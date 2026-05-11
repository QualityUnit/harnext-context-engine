"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";

type Result = { ok: true; id: string; at: string } | { ok: false; error: string };

export default function IngestPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-8 space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Ingest</h1>
        <p className="text-sm opacity-70 mt-1">
          Push something into the pipeline. Events flow through the worker into Graphiti.
        </p>
      </header>

      <FileUpload />
      <hr className="border-black/10 dark:border-white/10" />
      <JsonEvent />
    </div>
  );
}

function ResultBox({ result }: { result: Result | null }) {
  if (!result) return null;
  if (result.ok) {
    return (
      <div className="text-xs rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2">
        accepted · <code>{result.id}</code> · {new Date(result.at).toLocaleString()}
      </div>
    );
  }
  return (
    <div className="text-xs rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2">
      error: {result.error}
    </div>
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
    <section className="space-y-3">
      <h2 className="font-medium">Upload a file</h2>
      <p className="text-xs opacity-60">
        PDFs and text files get extracted in the worker. Other types are stored but not parsed in v0.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <input
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block text-sm"
        />
        <input
          type="text"
          placeholder="subject (optional, defaults to doc:<uuid>)"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          className="w-full text-sm bg-transparent border-b border-black/20 dark:border-white/20 outline-none py-1"
        />
        <button
          type="submit"
          disabled={!file || busy}
          className="text-sm px-3 py-1.5 rounded-md border border-black/15 dark:border-white/20 disabled:opacity-50"
        >
          {busy ? "uploading…" : "upload"}
        </button>
      </form>
      <ResultBox result={result} />
    </section>
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
    <section className="space-y-3">
      <h2 className="font-medium">Post a JSON event</h2>
      <form onSubmit={submit} className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="text-sm">
          <span className="opacity-70 text-xs">source</span>
          <input value={source} onChange={(e) => setSource(e.target.value)}
            className="w-full bg-transparent border-b border-black/20 dark:border-white/20 outline-none py-1" />
        </label>
        <label className="text-sm">
          <span className="opacity-70 text-xs">type</span>
          <input value={type} onChange={(e) => setType(e.target.value)}
            className="w-full bg-transparent border-b border-black/20 dark:border-white/20 outline-none py-1" />
        </label>
        <label className="text-sm">
          <span className="opacity-70 text-xs">subject</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)}
            className="w-full bg-transparent border-b border-black/20 dark:border-white/20 outline-none py-1" />
        </label>
        <label className="text-sm sm:col-span-3">
          <span className="opacity-70 text-xs">data (JSON)</span>
          <textarea
            value={dataText}
            onChange={(e) => setDataText(e.target.value)}
            rows={6}
            className="w-full font-mono text-xs bg-black/[0.04] dark:bg-white/[0.04] rounded-md p-2 outline-none"
          />
        </label>
        <div className="sm:col-span-3">
          <button
            type="submit"
            disabled={busy}
            className="text-sm px-3 py-1.5 rounded-md border border-black/15 dark:border-white/20 disabled:opacity-50"
          >
            {busy ? "posting…" : "post"}
          </button>
        </div>
      </form>
      <ResultBox result={result} />
    </section>
  );
}
