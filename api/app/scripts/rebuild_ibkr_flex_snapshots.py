"""Restore IBKR position/cash snapshots from retained Flex XMLs (#134).

Dry run by default; --apply writes. Prints counts per date, never amounts.
See app.portfolio.ibkr_flex_rebuild for what it does and does not touch.
"""
from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.portfolio.ibkr_flex_rebuild import rebuild_ibkr_flex_snapshots


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore IBKR position and cash snapshots that a multi-day Flex import deleted, "
        "from the raw Flex XMLs the earlier imports kept.",
    )
    parser.add_argument("--apply", action="store_true", help="Write the rows. Without it, only reports.")
    parser.add_argument(
        "--broker-account-id",
        type=int,
        default=None,
        help="Internal broker_accounts.id to rebuild (default: every IBKR account).",
    )
    parser.add_argument(
        "--raw-dir",
        default=None,
        help="Read the XMLs from this directory (by file name) instead of their stored path.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        results = rebuild_ibkr_flex_snapshots(
            db,
            apply=args.apply,
            broker_account_id=args.broker_account_id,
            raw_dir=args.raw_dir,
        )
    finally:
        db.close()

    mode = "APPLIED" if args.apply else "DRY RUN (pass --apply / APPLY=1 to write)"
    print(f"IBKR Flex snapshot rebuild: {mode}")
    if not results:
        print("No IBKR broker accounts found.")
    for result in results:
        print(
            f"broker_account {result.broker_account_id}: documents read={result.documents_read} "
            f"missing={result.documents_missing} rejected={result.documents_rejected}; "
            f"dates to restore={len(result.dates)} positions={result.positions_restored} "
            f"cash_balances={result.cash_balances_restored}"
        )
        for item in result.dates:
            upgraded = " completeness->complete" if item.completeness_upgraded else ""
            print(
                f"  {item.report_date.isoformat()} positions={item.positions} cash_balances={item.cash_balances} "
                f"from raw_document={item.raw_document_id} import_run={item.import_run_id}{upgraded}"
            )


if __name__ == "__main__":
    main()
