"""Re-type stored card currency-conversion fee rows as FEE (#308). Dry run by default;
--apply writes. Prints counts and row ids only. See app.ingestion.card_fee_repair."""
from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.ingestion.card_fee_repair import repair_card_fees, summary_lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify stored card conversion-fee rows as fees.")
    parser.add_argument("--apply", action="store_true", help="Write the changes. Without it, only reports.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = repair_card_fees(db, apply=args.apply)
    finally:
        db.close()
    for line in summary_lines(result, applied=args.apply):
        print(line)


if __name__ == "__main__":
    main()
