-- Migration 043: user-scoped author-ingestion realtime state and durable event history

ALTER TABLE rag_sources
    ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE rag_ingestion_jobs
    ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS batch_id UUID;

CREATE INDEX IF NOT EXISTS idx_rag_sources_user ON rag_sources (user_id);
CREATE INDEX IF NOT EXISTS idx_rag_jobs_user ON rag_ingestion_jobs (user_id);
CREATE INDEX IF NOT EXISTS idx_rag_jobs_batch ON rag_ingestion_jobs (batch_id);

CREATE TABLE IF NOT EXISTS realtime_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic           TEXT NOT NULL,
    event_name      TEXT NOT NULL,
    batch_id        UUID,
    author_id       TEXT,
    source_id       UUID,
    job_id          UUID,
    status          TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_realtime_events_user_topic_created
    ON realtime_events (user_id, topic, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_realtime_events_author
    ON realtime_events (author_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_realtime_events_source
    ON realtime_events (source_id, created_at DESC);
