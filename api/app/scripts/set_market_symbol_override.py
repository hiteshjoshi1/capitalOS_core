"""Set or clear one asset's Yahoo symbol override (#222).

Dry run by default; --apply writes. See app.market_data.symbol_override.
"""
from __future__ import annotations

import argparse
import sys

from app.db.session import SessionLocal
from app.market_data.symbol_override import SymbolOverrideError, set_yahoo_symbol_override


def main() -> None:
    parser = argparse.ArgumentParser(description="Quote an asset under another Yahoo symbol (e.g. <CODE>.BO).")
    parser.add_argument("--symbol", required=True, help="The asset's symbol (assets.symbol).")
    parser.add_argument("--currency", required=True, help="The asset's quote currency, e.g. INR.")
    parser.add_argument("--exchange", required=True, help="Exchange code: US, SGX, HKEX or NSE.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--yahoo", help="The Yahoo symbol to quote, with its suffix, e.g. ABC.BO.")
    target.add_argument("--clear", action="store_true", help="Remove the override.")
    parser.add_argument("--apply", action="store_true", help="Write the change. Without it, only reports.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = set_yahoo_symbol_override(
            db,
            symbol=args.symbol,
            currency=args.currency,
            exchange_code=args.exchange,
            yahoo_symbol=None if args.clear else args.yahoo,
            apply=args.apply,
        )
    except SymbolOverrideError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        sys.exit(2)
    finally:
        db.close()
    mode = "APPLIED" if result.applied else "DRY RUN (APPLY=1 to write)"
    print(f"Yahoo symbol override: {mode}")
    print(f"  asset {result.asset_id} on {result.exchange_code}: {result.action}")
    print(f"  override: {result.before or '(none)'} -> {result.after or '(none)'}; quoted as {result.quoted_as}")


if __name__ == "__main__":
    main()
