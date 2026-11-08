"""One-off IBKR Flex back-fill of an earlier period (#313). Dry run by default; --apply fetches
from IBKR. Prints windows and counts only, never the token. See app.portfolio.ibkr_flex_backfill.
"""
from __future__ import annotations

import argparse
from datetime import date

from app.db.session import SessionLocal
from app.portfolio.ibkr_flex_backfill import run_backfill, summary_lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch IBKR Flex statements for an earlier period and import them.")
    parser.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--query-id", default=None, help="A separate Flex query (default: the .env one)")
    parser.add_argument("--no-override", action="store_true", help="Use the query's own period (no fd/td)")
    parser.add_argument("--account", type=int, default=None, help="Legacy account id, when several")
    parser.add_argument("--apply", action="store_true", help="Fetch and import. Without it, only lists the requests.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        run = run_backfill(
            db,
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
            apply=args.apply,
            query_id=args.query_id,
            override_dates=not args.no_override,
            account_id=args.account,
        )
    finally:
        db.close()
    for line in summary_lines(run, applied=args.apply):
        print(line)


if __name__ == "__main__":
    main()
