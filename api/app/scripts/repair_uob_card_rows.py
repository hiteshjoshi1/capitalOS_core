"""Repair UOB card rows imported before #299's parser fix (duplicated period, amounts
replaced by the previous balance). Dry run by default; --apply writes. Prints counts and
ids only, never transaction details. See app.ingestion.uob_card_repair.
"""
from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.ingestion.uob_card_repair import repair_uob_card_rows, summary_lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-parse kept UOB card uploads and fix their stored rows.")
    parser.add_argument("--apply", action="store_true", help="Write the changes. Without it, only reports.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        results = repair_uob_card_rows(db, apply=args.apply)
    finally:
        db.close()
    for line in summary_lines(results, applied=args.apply):
        print(line)


if __name__ == "__main__":
    main()
