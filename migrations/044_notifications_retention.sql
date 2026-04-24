-- Migration 044: 6-month retention policy for realtime_events (system notifications)
--
-- The realtime_events table (created in migration 043) stores durable,
-- user-scoped notifications for the Alerts page.  Records are retained for
-- 180 days (~6 months) and then pruned by the daily background scheduler
-- that runs prune_old_realtime_events() in app/services/alerts.py.
--
-- No structural changes are required here because the table and indexes
-- already exist.  This migration documents the retention policy and adds a
-- partial index to accelerate the pruning DELETE query.

CREATE INDEX IF NOT EXISTS idx_realtime_events_created_at
    ON realtime_events (created_at);
