-- "Since your last visit" (#408, U3, D-112): when the user last looked at Overview, and the
-- net worth it showed then, so the next visit can say what changed (+S$ X, N imports since).
-- One row per user. A visit only moves the mark when the previous one is over
-- LAST_VISIT_MIN_GAP old (app/services/last_visit.py), or the user dismisses the strip,
-- so reloading Overview within a session keeps showing the same comparison.
CREATE TABLE IF NOT EXISTS user_last_visit (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  seen_at TIMESTAMPTZ NOT NULL,
  net_worth NUMERIC(38, 2),
  base_currency TEXT
);
