-- Migration 057: Retire legacy positions as read-only archive.
-- Non-destructive: preserves the table and existing data, but blocks new
-- authoritative writes so canonical portfolio facts remain the only write path.

-- Older dummy seeds wrote demo portfolio rows to positions. Remove only those
-- generated rows before installing the guard so db-seed-dummy can be re-run
-- against databases that had pre-183 demo data.
DELETE FROM positions p
USING accounts a
WHERE a.id = p.account_id
  AND a.name LIKE 'DUMMY - %';

CREATE OR REPLACE FUNCTION prevent_legacy_positions_write()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION
    'legacy positions is retired and read-only; write canonical portfolio facts instead'
    USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_legacy_positions_insert ON positions;
DROP TRIGGER IF EXISTS trg_prevent_legacy_positions_update ON positions;
DROP TRIGGER IF EXISTS trg_prevent_legacy_positions_delete ON positions;

CREATE TRIGGER trg_prevent_legacy_positions_insert
BEFORE INSERT ON positions
FOR EACH ROW EXECUTE FUNCTION prevent_legacy_positions_write();

CREATE TRIGGER trg_prevent_legacy_positions_update
BEFORE UPDATE ON positions
FOR EACH ROW EXECUTE FUNCTION prevent_legacy_positions_write();

CREATE TRIGGER trg_prevent_legacy_positions_delete
BEFORE DELETE ON positions
FOR EACH ROW EXECUTE FUNCTION prevent_legacy_positions_write();
