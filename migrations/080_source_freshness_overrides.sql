-- Source freshness (#252, D-67): a user's own expected cadence for one data source.
--
-- The Data Hub lists one row per source (an account, a crypto wallet, a quote feed
-- per exchange, the FX feed) with its newest data date and whether it is overdue.
-- Each source type has a default cadence in the code (app/services/source_freshness.py);
-- a row here overrides it for one source of one user. `source_key` is the API's key:
-- 'account:<id>', 'wallet:<uuid>', 'exchange:<code>' or 'fx'. Only internal ids.
--
-- `cadence` is how often new data is expected ('off': never overdue); `grace_days` how
-- long after that before the source counts as overdue (business days for 'weekdays',
-- calendar days otherwise). No row: the default applies.
CREATE TABLE IF NOT EXISTS source_freshness_overrides (
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source_key TEXT NOT NULL,
  cadence TEXT NOT NULL CHECK (cadence IN ('daily', 'weekdays', 'weekly', 'monthly', 'quarterly', 'off')),
  grace_days INTEGER NOT NULL CHECK (grace_days BETWEEN 0 AND 90),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, source_key)
);
