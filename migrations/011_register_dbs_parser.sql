INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES (
  '5bc051e1926689030f7446adf347888f588dc01cd0eef9025357c99b4495038e',
  'dbs_transaction_history_csv_v1',
  1
)
ON CONFLICT (format_signature) DO NOTHING;
