-- #140 / migration 075: "same authoritative rows before and after". Read-only.
--
-- Run on a test copy BEFORE applying 075 and again AFTER, e.g.
--   docker exec -i <postgres container> psql -U capitalos -d capitalos -At -F ' | ' \
--     < scripts/authority-windows-075-check.sql > before.txt   (then after.txt)
--
-- Per fact table it prints two fingerprints of the rows that count:
--   old_rule = authority_status 'authoritative' OR inside an IBKR Flex window (the
--              readers' rule before #140)
--   status   = authority_status 'authoritative' (the readers' rule after #140)
-- Pass: AFTER's old_rule and status columns both equal BEFORE's old_rule columns.
-- (BEFORE's status columns are smaller by exactly the rows 075 promotes.)
-- Per (broker account, source, scope) it prints the dates the authoritative
-- windows cover as one range; it must be the same before and after (only the
-- number of window rows, last column, drops to 1).

WITH flex_window AS (
  SELECT broker_account_id, effective_from, effective_to
  FROM portfolio_source_authority_windows
  WHERE source_kind = 'ibkr_flex_daily' AND fact_scope = 'all' AND authority_status = 'authoritative'
),
facts AS (
  SELECT 'positions' AS facts, t.id, t.authority_status, t.broker_account_id, t.report_date
  FROM portfolio_position_snapshots t
  UNION ALL
  SELECT 'cash', t.id, t.authority_status, t.broker_account_id, t.report_date
  FROM portfolio_cash_balance_snapshots t
  UNION ALL
  SELECT 'nav', t.id, t.authority_status, t.broker_account_id, t.report_date
  FROM portfolio_nav_snapshots t
),
judged AS (
  SELECT
    f.facts,
    f.id,
    f.authority_status = 'authoritative' AS by_status,
    f.authority_status = 'authoritative' OR EXISTS (
      SELECT 1 FROM flex_window aw
      WHERE aw.broker_account_id = f.broker_account_id
        AND aw.effective_from <= f.report_date
        AND (aw.effective_to IS NULL OR aw.effective_to >= f.report_date)
    ) AS by_old_rule
  FROM facts f
)
SELECT
  'facts ' || facts AS item,
  (COUNT(*) FILTER (WHERE by_old_rule))::text AS old_rule_rows,
  COALESCE(md5(string_agg(id::text, ',' ORDER BY id) FILTER (WHERE by_old_rule)), '-') AS old_rule_ids,
  (COUNT(*) FILTER (WHERE by_status))::text AS status_rows,
  COALESCE(md5(string_agg(id::text, ',' ORDER BY id) FILTER (WHERE by_status)), '-') AS status_ids,
  '' AS window_rows
FROM judged
GROUP BY facts
UNION ALL
SELECT
  'window ' || broker_account_id || ' ' || source_kind || '/' || fact_scope,
  MIN(effective_from)::text,
  CASE WHEN COUNT(*) > COUNT(effective_to) THEN 'open' ELSE MAX(effective_to)::text END,
  '',
  '',
  COUNT(*)::text
FROM portfolio_source_authority_windows
WHERE authority_status = 'authoritative'
GROUP BY broker_account_id, source_kind, fact_scope
ORDER BY 1;
