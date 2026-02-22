INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES (
  '82b75b5ae69978f8b967f3101980eb6b6ec7327e76383a430cee2b10f7361b31',
  'sharekhan_holdings_xls_v1',
  1
)
ON CONFLICT (format_signature) DO NOTHING;
