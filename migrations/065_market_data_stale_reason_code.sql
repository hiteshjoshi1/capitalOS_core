ALTER TABLE market_data_run_items
  ADD COLUMN IF NOT EXISTS reason_code TEXT;

UPDATE market_data_run_items
SET reason_code = CASE
  WHEN status = 'invalid' THEN 'INVALID_PRICE'
  WHEN source_note ~* '(^|[^0-9])429([^0-9]|$)|rate[ -]?limit' THEN 'RATE_LIMITED'
  WHEN status = 'missing' AND source_note IS NULL THEN 'NO_TRADE_REPORTED'
  ELSE 'PROVIDER_ERROR'
END
WHERE status IN ('missing', 'invalid')
  AND reason_code IS NULL;

ALTER TABLE market_data_run_items
  ADD CONSTRAINT market_data_run_items_reason_code_check
  CHECK (reason_code IS NULL OR reason_code IN (
    'RATE_LIMITED',
    'NO_TRADE_REPORTED',
    'PROVIDER_ERROR',
    'INVALID_PRICE'
  ));

ALTER TABLE market_data_run_items
  ADD CONSTRAINT market_data_run_items_failed_reason_code_check
  CHECK (status NOT IN ('missing', 'invalid') OR reason_code IS NOT NULL);
