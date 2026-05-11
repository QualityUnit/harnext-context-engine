// Wire types matching the backend API. Keep in lock-step with apps/api/src/meaninggrid_api/routes/.

export type EventSummary = {
  id: string;
  source: string;
  type: string;
  subject: string;
  event_time: string;
  ingest_time: string;
  has_blob: boolean;
};

export type SinkStatus = {
  sink: string;
  status: "pending" | "success" | "failed" | string;
  attempts: number;
  last_error: string | null;
  completed_at: string | null;
};

export type EventDetail = EventSummary & {
  envelope_json: string;
  sinks: SinkStatus[];
};

export type GraphNode = {
  id: string;
  kind: string;
  name: string;
  summary: string | null;
  labels: string[];
  valid_at: string | null;
  invalid_at: string | null;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  fact: string;
  valid_at: string | null;
  invalid_at: string | null;
  episode_uuid: string | null;
};

export type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type EntitySearchHit = {
  fact: string;
  valid_at: string | null;
  source_node: string;
  target_node: string;
};

export type IngestResponse = {
  id: string;
  accepted_at: string;
};
