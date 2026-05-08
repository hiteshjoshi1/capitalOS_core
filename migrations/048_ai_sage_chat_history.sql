-- Migration 048: AI Sage persistent chat history and retention indexes

CREATE TABLE IF NOT EXISTS ai_sage_chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pinned_at TIMESTAMPTZ,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_sage_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES ai_sage_chats(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    metadata_json JSONB
);

CREATE TABLE IF NOT EXISTS ai_sage_turn_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES ai_sage_messages(id) ON DELETE CASCADE,
    chunk_id TEXT,
    document_id TEXT,
    author_id TEXT,
    author_name TEXT,
    source_url TEXT,
    title TEXT,
    snippet TEXT,
    similarity DOUBLE PRECISION,
    ranking_score DOUBLE PRECISION,
    score_type TEXT,
    metadata_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_ai_sage_chats_owner_updated
    ON ai_sage_chats (owner_user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_sage_chats_owner_last_activity
    ON ai_sage_chats (owner_user_id, last_activity_at);

CREATE INDEX IF NOT EXISTS idx_ai_sage_messages_chat_created
    ON ai_sage_messages (chat_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_ai_sage_turn_evidence_message
    ON ai_sage_turn_evidence (message_id);
