// Health and live-update messages: response and request types (split out of lib/api.ts, #368).

export type Health = {
  status: string;
  /** #155: "ok", or "unreachable" (with HTTP 503). */
  database?: string;
  /** #155: newest applied migration vs the newest migration file; current is null when either is unknown. */
  migrations?: { applied: string | null; latest_file: string | null; current: boolean | null };
};

export type RealtimeEventEnvelope<TPayload = Record<string, unknown>> = {
  id: string;
  topic: string;
  event_name: string;
  batch_id?: string | null;
  author_id?: string | null;
  source_id?: string | null;
  job_id?: string | null;
  status?: string | null;
  created_at?: string | null;
  payload: TPayload;
};
