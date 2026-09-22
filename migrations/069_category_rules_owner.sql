-- Category rules were a single global table: any authenticated user could list,
-- change or deactivate every rule, and every rule applied to every user.
--
-- user_id NULL  = shared system rule (the migration-seeded defaults). Visible to
--                 and applied for everyone, but only an admin may change it.
-- user_id = N   = rule created by user N. Visible, editable and applied only for
--                 that user's transactions.
--
-- Existing rows keep user_id NULL, i.e. they stay shared system defaults.
ALTER TABLE category_rules
  ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_category_rules_user_id
  ON category_rules (user_id);
