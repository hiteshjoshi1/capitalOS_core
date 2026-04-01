-- Enforce strict account ownership.
-- If this fails, run ownership reassignment first:
--   python -m app.scripts.reassign_legacy_ownership --target-user-id <id>

DO $$
DECLARE
  null_count BIGINT;
BEGIN
  SELECT COUNT(*) INTO null_count
  FROM accounts
  WHERE user_id IS NULL;

  IF null_count > 0 THEN
    RAISE EXCEPTION
      'Cannot enforce accounts.user_id NOT NULL. Found % NULL account owner(s). Reassign legacy ownership first.',
      null_count;
  END IF;
END $$;

ALTER TABLE accounts
  ALTER COLUMN user_id SET NOT NULL;
