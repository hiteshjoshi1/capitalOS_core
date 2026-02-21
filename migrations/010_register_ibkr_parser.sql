INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES (
  '13ab5e16819c44d6fccb2e2a59ce17653eacd535e42b683c3de3fe7c54750199',
  'ibkr_activity_csv_v1',
  1
)
ON CONFLICT (format_signature) DO NOTHING;
