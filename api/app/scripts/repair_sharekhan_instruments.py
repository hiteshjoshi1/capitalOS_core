"""Repair Sharekhan instruments imported with ticker and name swapped (#222).

Dry run by default; --apply writes. Prints counts and instrument/account ids,
never holdings. See app.portfolio.sharekhan_instrument_repair.
"""
from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.portfolio.sharekhan_instrument_repair import repair_sharekhan_instruments, summary_lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix ticker/name on SHAREKHAN instruments and link them to INR assets so they get priced.",
    )
    parser.add_argument("--apply", action="store_true", help="Write the changes. Without it, only reports.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = repair_sharekhan_instruments(db, apply=args.apply)
    finally:
        db.close()
    for line in summary_lines(result):
        print(line)


if __name__ == "__main__":
    main()
