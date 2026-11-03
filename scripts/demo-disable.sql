-- Turn the demo login off again (#152): `make demo-disable`. Same as migration 072.
UPDATE auth_sessions
SET revoked_at = NOW(), revoke_reason = 'demo_disabled'
WHERE revoked_at IS NULL
  AND user_id IN (SELECT id FROM users WHERE LOWER(username) = 'demo');

UPDATE users SET is_active = FALSE, updated_at = NOW()
WHERE LOWER(username) = 'demo' AND is_active;

UPDATE user_credentials
SET password_hash = '!', password_algo = 'disabled', password_updated_at = NOW()
WHERE user_id IN (SELECT id FROM users WHERE LOWER(username) = 'demo')
  AND password_hash <> '!';
