INSERT INTO crypto_allowlist (chain, contract_address, symbol, name)
VALUES
  ('solana', 'epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v', 'USDC', 'USD Coin'),
  ('solana', 'es9vmfrzacerjmjrf4h2fyd4kconky11mcce8benwnyb', 'USDT', 'Tether USD')
ON CONFLICT (chain, contract_address) DO UPDATE
  SET symbol = EXCLUDED.symbol, name = EXCLUDED.name;
