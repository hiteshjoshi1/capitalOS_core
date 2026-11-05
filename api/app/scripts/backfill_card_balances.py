"""Backfill dated card statement balances from the stored card statements (#207).

Dry run by default; --apply writes. Prints counts, job ids and dates, never amounts.
See app.ingestion.card_balance_backfill.
"""
from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.ingestion.card_balance_backfill import backfill_card_balances, summary_lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write each stored card statement's balance as a dated credit_balance snapshot.",
    )
    parser.add_argument("--apply", action="store_true", help="Write the rows. Without it, only reports.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = backfill_card_balances(db, apply=args.apply)
    finally:
        db.close()
    for line in summary_lines(result):
        print(line)


if __name__ == "__main__":
    main()
