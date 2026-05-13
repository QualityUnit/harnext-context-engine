import Link from "next/link";

const cards = [
  {
    href: "/events",
    title: "Events",
    body: "What's been ingested. Per-event sink processing status.",
  },
  {
    href: "/graph",
    title: "Graph",
    body: "The semantic graph Graphiti built. Cytoscape-rendered subgraph of recent activity.",
  },
  {
    href: "/documents",
    title: "Documents",
    body: "2D map of every ingested document by embedding similarity (FAISS + PCA).",
  },
  {
    href: "/ingest",
    title: "Ingest",
    body: "Upload a document or post a JSON event to feed the pipeline.",
  },
];

export default function Home() {
  return (
    <div className="max-w-6xl mx-auto px-6 py-12 space-y-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">meaninggrid</h1>
        <p className="opacity-70">
          v0 dashboard. See <code>docs/architecture/</code> for the architecture.
        </p>
      </header>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {cards.map((c) => (
          <Link
            key={c.href}
            href={c.href}
            className="block p-5 rounded-lg border border-black/10 dark:border-white/15 hover:bg-black/[0.03] dark:hover:bg-white/[0.04] transition"
          >
            <div className="font-medium mb-1">{c.title}</div>
            <div className="text-sm opacity-70">{c.body}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
