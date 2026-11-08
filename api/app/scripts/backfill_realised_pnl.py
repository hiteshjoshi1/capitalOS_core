"""Fill IBKR's realised P&L and FX rate into trades stored before #293. Dry run by
default; --apply writes. Counts only. See app.portfolio.realised_backfill."""
from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.portfolio.realised_backfill import backfill_realised, summary_lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-read kept IBKR Flex reports into stored trades' metadata.")
    parser.add_argument("--apply", action="store_true", help="Write the changes. Without it, only reports.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = backfill_realised(db, apply=args.apply)
    finally:
        db.close()
    for line in summary_lines(result, applied=args.apply):
        print(line)


if __name__ == "__main__":
    main()
