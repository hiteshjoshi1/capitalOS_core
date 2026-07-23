# Sanitized ingestion fixtures

These files are deterministic, synthetic test data. They preserve the bank-export
structures and parser edge cases used by the ingestion tests without containing
real names, account numbers, card numbers, references, or transaction histories.
Public bank/product and merchant-category keywords appear only where a parser
requires them to exercise deterministic classification behavior.

The card-like values use published payment-network test numbers or clearly fake
zero-prefixed identifiers. They must never be replaced with production exports.

Run `python generate_sanitized_fixtures.py` in an environment containing
`openpyxl` to regenerate all five fixtures.
