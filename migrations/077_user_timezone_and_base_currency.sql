-- Per-user timezone and server-side base currency (#202).
--
-- timezone: the user's home timezone (IANA name, validated by the API against
--   zoneinfo). Month logic follows it: which month is open, when a month's
--   anchor passes, History completion and the card-transaction month boundary.
--   NULL means "the app's TZ" (env TZ, default Asia/Singapore).
-- timezone_from_app: TRUE for every user that existed before this migration.
--   They keep following the app's TZ (so their numbers don't change) until they
--   pick a timezone in Settings. A user created later starts FALSE with a NULL
--   timezone, which the web app fills from the browser on first sign-in.
-- base_currency: the #150 follow-up. NULL until the user (or their browser's
--   saved choice) sets it; the per-browser value stays the first paint.
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS timezone TEXT;
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS timezone_from_app BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS base_currency TEXT;

ALTER TABLE user_preferences DROP CONSTRAINT IF EXISTS user_preferences_base_currency_format;
ALTER TABLE user_preferences ADD CONSTRAINT user_preferences_base_currency_format
    CHECK (base_currency IS NULL OR base_currency ~ '^[A-Z]{3}$');

-- Every existing user gets a row (create-on-read never ran for some), marked as
-- following the app's TZ.
INSERT INTO user_preferences (user_id)
SELECT u.id FROM users u
WHERE NOT EXISTS (SELECT 1 FROM user_preferences p WHERE p.user_id = u.id);

UPDATE user_preferences SET timezone_from_app = TRUE WHERE timezone IS NULL;
