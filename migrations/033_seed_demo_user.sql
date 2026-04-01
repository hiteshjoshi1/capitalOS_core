-- Seed a dedicated demo identity used for demo-only data ownership.
-- Demo credentials:
--   username: demo
--   password: Test@1234

INSERT INTO users (username, display_name, email, is_active, is_admin)
VALUES ('demo', 'Demo User', 'demo@capitalos.local', TRUE, FALSE)
ON CONFLICT (username) DO UPDATE
SET
  display_name = EXCLUDED.display_name,
  email = EXCLUDED.email,
  is_active = EXCLUDED.is_active,
  is_admin = EXCLUDED.is_admin,
  updated_at = NOW();

INSERT INTO user_credentials (user_id, password_hash, password_algo, password_updated_at)
SELECT
  id,
  'pbkdf2_sha256$260000$0123456789abcdeffedcba9876543210$5a71fa4bc2ecf23a8de76d2f5897299dbab66f2cfea1080b03c2d675eea47373',
  'pbkdf2_sha256',
  NOW()
FROM users
WHERE LOWER(username) = 'demo'
ON CONFLICT (user_id) DO UPDATE
SET
  password_hash = EXCLUDED.password_hash,
  password_algo = EXCLUDED.password_algo,
  password_updated_at = EXCLUDED.password_updated_at;
