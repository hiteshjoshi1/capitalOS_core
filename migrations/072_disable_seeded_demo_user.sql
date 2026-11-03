-- #152: the demo login seeded by 033 (published password) must not work on a real install.
-- Deactivate it and sign out its sessions. Its data stays (it owns the demo/dummy rows).
-- Dev/test stacks turn it back on with `make demo-enable` (scripts/demo-enable.sql), which
-- refuses on the real-data stack. Idempotent: re-running changes nothing further.

UPDATE auth_sessions
SET revoked_at = NOW(), revoke_reason = 'demo_disabled'
WHERE revoked_at IS NULL
  AND user_id IN (SELECT id FROM users WHERE LOWER(username) = 'demo');

UPDATE users
SET is_active = FALSE, updated_at = NOW()
WHERE LOWER(username) = 'demo'
  AND is_active;

-- And forget the published password: an account turned back on by hand (is_active = TRUE)
-- still can't sign in with it. '!' is not a valid hash, so no password matches it.
UPDATE user_credentials
SET password_hash = '!', password_algo = 'disabled', password_updated_at = NOW()
WHERE user_id IN (SELECT id FROM users WHERE LOWER(username) = 'demo')
  AND password_hash <> '!';
