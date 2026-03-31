-- Seed a dedicated demo identity used for demo-only data ownership.
-- Credentials are intentionally not seeded here; they are created via app auth flows.

INSERT INTO users (username, display_name, email, is_active, is_admin)
VALUES ('demo', 'Demo User', 'demo@capitalos.local', TRUE, FALSE)
ON CONFLICT (username) DO NOTHING;
