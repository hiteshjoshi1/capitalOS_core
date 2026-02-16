CREATE TABLE IF NOT EXISTS currencies (
  id        BIGSERIAL PRIMARY KEY,
  code      TEXT NOT NULL UNIQUE,
  name      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO currencies (code, name) VALUES
  ('SGD', 'Singapore Dollar'),
  ('USD', 'US Dollar'),
  ('INR', 'Indian Rupee')
ON CONFLICT (code) DO NOTHING;
