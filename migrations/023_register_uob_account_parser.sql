INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES (
  'd648dffea3a088441247548b7e50a3cf9e338efc1571aa0b37d8b625ee783770',
  'uob_account_xls_v1',
  1
)
ON CONFLICT (format_signature) DO NOTHING;
