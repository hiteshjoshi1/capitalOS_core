WITH mapped AS (
  SELECT DISTINCT ON (m.asset_id)
    m.asset_id,
    CASE UPPER(m.exchange_code)
      WHEN 'US' THEN 'US'
      WHEN 'HKEX' THEN 'HK'
      WHEN 'NSE' THEN 'IN'
      WHEN 'SGX' THEN 'SG'
      ELSE NULL
    END AS inferred_country
  FROM market_symbol_map m
  WHERE m.is_active = TRUE
  ORDER BY
    m.asset_id,
    CASE UPPER(m.exchange_code)
      WHEN 'US' THEN 1
      WHEN 'HKEX' THEN 2
      WHEN 'NSE' THEN 3
      WHEN 'SGX' THEN 4
      ELSE 99
    END
)
UPDATE assets a
SET home_country = mapped.inferred_country
FROM mapped
WHERE a.id = mapped.asset_id
  AND a.home_country IS NULL
  AND mapped.inferred_country IS NOT NULL;
