// Zero-dependency mock of the ingest API, just rich enough to render the project
// dashboard and exercise per-view routing in e2e tests and manual Chrome DevTools
// checks. Start with: node e2e/mock-api.mjs [port]   (default 8000)
import { createServer } from "node:http";

const PORT = Number(process.argv[2] ?? process.env.MOCK_API_PORT ?? 8000);

const project = (id, name) => ({
  id,
  name,
  owner_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  github_login: "octocat",
  github_connected: true,
  slack_team_name: null,
  slack_connected: false,
  discord_guild_name: null,
  discord_connected: false,
  liveagent_base_url: null,
  liveagent_connected: false,
});

const PROJECTS = [project("p1", "acme-engineering"), project("p2", "side-project")];

const analytics = {
  events_per_day: [3, 5, 2, 8, 6, 4, 7],
  total_events: 35,
  total_builds: 12,
  context_bytes: 184320,
  sources_live: 1,
  days: 7,
};

const mcpStats = {
  requests_per_day: [1, 0, 4, 2, 3, 5, 2],
  total_requests: 17,
  total_errors: 1,
  avg_duration_ms: 42,
  by_tool: { search: 10, fetch: 7 },
  days: 7,
};

const mcpRequests = [
  {
    id: "r1",
    tool: "search",
    params: { query: "deploy" },
    status: "ok",
    response: { hits: 3 },
    error: null,
    duration_ms: 38,
    created_at: "2026-06-09T10:00:00Z",
  },
];

const sources = [
  {
    id: "s1",
    org_id: "p1",
    kind: "github",
    config: { repo: "octocat/hello-world" },
    status: "live",
    cursor: null,
    last_sync_at: "2026-06-09T09:00:00Z",
    last_error: null,
    created_at: "2026-01-02T00:00:00Z",
    has_secret: true,
    event_count: 35,
  },
];

const health = {
  ok: true,
  kinds: ["github", "slack", "discord", "liveagent", "youtube", "url"],
  oauth: { github: true, slack: true, discord: true, google: true },
};

// The agent's context filesystem (seed layout) for the Files view.
const fsList = {
  files: [
    "CLAUDE.md",
    "INDEX.md",
    "_meta/schema.md",
    "_meta/superseded.md",
    "entities/.gitkeep",
    "topics/.gitkeep",
  ],
  snapshot_id: "snap-test",
};

const fsFile = { path: "INDEX.md", content: "# Org Context Index\n", size: 20 };

// Resolve a GET path (querystring stripped) to a JSON body. Returns undefined
// for unknown routes so the caller can 404.
function route(pathname) {
  if (pathname === "/health") return health;
  if (pathname === "/projects") return PROJECTS;

  const m = pathname.match(/^\/projects\/([^/]+)(\/.*)?$/);
  if (m) {
    const id = m[1];
    const rest = m[2] ?? "";
    const proj = PROJECTS.find((p) => p.id === id) ?? project(id, id);
    if (rest === "") return proj;
    if (rest === "/analytics") return analytics;
    if (rest === "/mcp") return { endpoint: `http://localhost:8765/mcp/${id}`, token: "mcp-test-token" };
    if (rest === "/mcp-requests") return mcpRequests;
    if (rest === "/mcp-requests/stats") return mcpStats;
    if (rest === "/fs") return fsList;
    if (rest === "/fs/file") return fsFile;
  }

  if (pathname === "/sources") return sources;
  // Connector pickers (only hit when a modal opens) — empty lists are fine.
  if (/\/(repos|channels|departments|tags)$/.test(pathname)) return [];
  return undefined;
}

const server = createServer((req, res) => {
  const cors = {
    "Access-Control-Allow-Origin": req.headers.origin ?? "*",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
  };
  if (req.method === "OPTIONS") {
    res.writeHead(204, cors);
    res.end();
    return;
  }

  const { pathname } = new URL(req.url, `http://localhost:${PORT}`);

  // Mutations the dashboard fires (sync/delete/rename/disconnect) — just ack so
  // the UI's optimistic refresh has something to re-read.
  if (req.method !== "GET") {
    res.writeHead(200, { ...cors, "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
    return;
  }

  const body = route(pathname);
  if (body === undefined) {
    res.writeHead(404, { ...cors, "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: `no mock for ${pathname}` }));
    return;
  }
  res.writeHead(200, { ...cors, "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
});

server.listen(PORT, () => console.log(`mock-api listening on http://localhost:${PORT}`));
