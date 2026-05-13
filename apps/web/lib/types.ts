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

export type DocumentPoint = {
  event_id: string;
  source: string;
  type: string;
  subject: string;
  event_time: string;
  ingest_time: string;
  text_preview: string | null;
  x: number;
  y: number;
};

export type DocumentMap = {
  points: DocumentPoint[];
  method: string;
  variance_explained: [number, number];
};

export type HfDataset = {
  key: string;
  label: string;
  dataset_id: string;
  description: string;
  total_rows: number;
};

export type HfIngestResponse = {
  job_id: string;
  dataset_id: string;
  dataset_key: string;
  target: number;
};

export type HfJobStatus = {
  job_id: string;
  dataset_id: string;
  dataset_key: string;
  state: "queued" | "downloading" | "importing" | "done" | "failed" | string;
  target: number;
  accepted: number;
  skipped: number;
  current_part: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type ResetSummary = {
  falkordb_graphs: string[];
  sqlite_rows_before: Record<string, number>;
  minio_objects: number;
  faiss_files: number;
  kafka_topics: string[];
  tenants_reseeded: string[];
  notes: string[];
};
