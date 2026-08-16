-- IBKR reports a HKEX position (symbol '168', TSINGTAO BREWERY CO LTD-H) that never
-- got an assets/market_symbol_map row, so it silently never received an independent
-- market-data price refresh (positions/NAV totals were still correct via IBKR's own
-- reported value; only the price-overlay/freshness layer was missing).
INSERT INTO assets (symbol, name, asset_class, quote_currency, home_country)
SELECT '168', 'Tsingtao Brewery Co Ltd-H', 'STOCK', 'HKD', 'HK'
WHERE NOT EXISTS (SELECT 1 FROM assets WHERE symbol = '168');

INSERT INTO market_symbol_map (asset_id, exchange_code, exchange_symbol, quote_currency, is_active)
SELECT a.id, 'HKEX', '168', 'HKD', TRUE
FROM assets a
WHERE a.symbol = '168'
  AND NOT EXISTS (
    SELECT 1 FROM market_symbol_map m WHERE m.asset_id = a.id AND m.exchange_code = 'HKEX'
  );
