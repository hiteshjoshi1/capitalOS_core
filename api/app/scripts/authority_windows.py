"""List or move source authority windows (#140).

    python -m app.scripts.authority_windows list [--broker-account-id N]
    python -m app.scripts.authority_windows move --broker-account-id N --effective-from YYYY-MM-DD \
        --reason "..." [--source-kind ibkr_flex_daily] [--fact-scope all] [--effective-to YYYY-MM-DD | --open] [--apply]

`move` is the only way a window's dates change: imports never move one. It is a
dry run unless --apply is given; with --apply it logs the change, restamps that
source's facts on the broker account and marks History dirty. Prints dates and
row counts, never amounts.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import date

from app.db.session import SessionLocal
from app.portfolio.authority import (
    FLEX_FACT_SCOPE,
    FLEX_SOURCE_KIND,
    KEEP_END,
    AuthorityWindowError,
    list_windows,
    move_window,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List or move source authority windows.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="Show the windows.")
    list_cmd.add_argument("--broker-account-id", type=int, default=None, help="Internal broker_accounts.id.")

    move = sub.add_parser("move", help="Move (or close) one window. Dry run without --apply.")
    move.add_argument("--broker-account-id", type=int, required=True, help="Internal broker_accounts.id.")
    move.add_argument("--source-kind", default=FLEX_SOURCE_KIND)
    move.add_argument("--fact-scope", default=FLEX_FACT_SCOPE)
    move.add_argument("--effective-from", type=date.fromisoformat, required=True)
    end = move.add_mutually_exclusive_group()
    end.add_argument("--effective-to", type=date.fromisoformat, default=None, help="Close the window on this date.")
    end.add_argument("--open", action="store_true", help="Leave the window open-ended.")
    move.add_argument("--reason", required=True, help="Why: recorded in the change log.")
    move.add_argument("--apply", action="store_true", help="Write. Without it, only reports.")
    return parser


def _fmt(value: date | None) -> str:
    return value.isoformat() if value else "open"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        if args.command == "list":
            windows = list_windows(db, args.broker_account_id)
            if not windows:
                print("No authority windows.")
            for w in windows:
                print(
                    f"window {w.id}: broker_account {w.broker_account_id} {w.source_kind}/{w.fact_scope} "
                    f"{w.effective_from.isoformat()} .. {_fmt(w.effective_to)} [{w.authority_status}]"
                )
            return 0

        if args.open:
            effective_to: object = None
        elif args.effective_to is not None:
            effective_to = args.effective_to
        else:
            effective_to = KEEP_END
        try:
            result = move_window(
                db,
                broker_account_id=args.broker_account_id,
                source_kind=args.source_kind,
                fact_scope=args.fact_scope,
                effective_from=args.effective_from,
                effective_to=effective_to,
                reason=args.reason,
                actor=f"cli:{getpass.getuser()}",
                apply=args.apply,
            )
        except AuthorityWindowError as exc:
            db.rollback()
            print(f"Refused: {exc}", file=sys.stderr)
            return 1
        if args.apply:
            db.commit()
        mode = "APPLIED" if args.apply else "DRY RUN (pass --apply / APPLY=1 to write)"
        before = result.before
        print(f"Authority window move: {mode}")
        print(
            f"  {args.source_kind}/{args.fact_scope} on broker_account {args.broker_account_id}: "
            + (f"{before.effective_from.isoformat()} .. {_fmt(before.effective_to)}" if before else "none")
            + f" -> {result.after.effective_from.isoformat()} .. {_fmt(result.after.effective_to)}"
        )
        for table in sorted(set(result.rows_promoted) | set(result.rows_demoted)):
            print(
                f"  {table}: to authoritative={result.rows_promoted.get(table, 0)} "
                f"to reference={result.rows_demoted.get(table, 0)}"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
