from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.services.ownership import reassign_legacy_ownership


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reassign legacy NULL-owned records to a target user id.",
    )
    parser.add_argument("--target-user-id", type=int, required=True, help="Destination user id")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates. Without this flag, runs in dry-run preview mode.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        result = reassign_legacy_ownership(
            db,
            target_user_id=args.target_user_id,
            dry_run=not args.apply,
        )
        print(
            json.dumps(
                {
                    "dry_run": not args.apply,
                    "target_user_id": args.target_user_id,
                    "accounts_updated": result.accounts_updated,
                    "wallets_updated": result.wallets_updated,
                    "crypto_networth_updated": result.crypto_networth_updated,
                },
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

