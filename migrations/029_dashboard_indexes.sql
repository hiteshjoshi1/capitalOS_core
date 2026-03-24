-- Migration 029: Dashboard query indexes
-- Targets the three hottest dashboard query patterns.

CREATE INDEX IF NOT EXISTS idx_positions_as_of
    ON positions (as_of);

CREATE INDEX IF NOT EXISTS idx_positions_account_id_as_of
    ON positions (account_id, as_of DESC);

CREATE INDEX IF NOT EXISTS idx_crypto_wallet_snapshot_items_snapshot_id
    ON crypto_wallet_snapshot_items (snapshot_id);
