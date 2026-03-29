-- Extend category taxonomy with additional expense categories.
-- Idempotent inserts to support repeated migration runs.

INSERT INTO category_taxonomy (code, name, parent_id, display_order)
VALUES
  ('education', 'Education', NULL, 65)
ON CONFLICT (code) DO NOTHING;

WITH parent_rows AS (
  SELECT id, code
  FROM category_taxonomy
)
INSERT INTO category_taxonomy (code, name, parent_id, display_order)
VALUES
  ('housing_rent', 'Rent', (SELECT id FROM parent_rows WHERE code = 'housing'), 21),
  ('education_school_fees', 'School Fees', (SELECT id FROM parent_rows WHERE code = 'education'), 66),
  ('health_gym', 'Gym', (SELECT id FROM parent_rows WHERE code = 'health'), 62)
ON CONFLICT (code) DO NOTHING;
