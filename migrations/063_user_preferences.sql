-- User display preferences: theme and accent colour
-- One row per user, created on first read (create-on-read pattern in GET /auth/preferences).
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id     BIGINT      PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme       TEXT        NOT NULL DEFAULT 'dark',
    accent_color TEXT       NOT NULL DEFAULT '#0f7a5c',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
