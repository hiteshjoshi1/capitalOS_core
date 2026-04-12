-- Add revoke_reason to auth_sessions so we can distinguish rotation from logout.
-- Values: 'rotation' (token was rotated during refresh), 'logout' (explicit logout),
--         'security' (admin/security invalidation). NULL = legacy rows.
ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS revoke_reason TEXT;
