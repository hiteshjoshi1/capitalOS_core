"""Back-fill past crypto prices into wallet snapshots (#331). Dry run by default; --apply
fetches from DefiLlama (capped per run; run again to continue). Prints counts only.
See app.crypto.price_backfill."""
from __future__ import annotations

import argparse

from sqlalchemy import text

from app.crypto.price_backfill import run_backfill
from app.db.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch historical prices for wallet snapshot items with none.")
    parser.add_argument("--apply", action="store_true", help="Fetch and store. Without it, only reports.")
    parser.add_argument("--user-id", type=int, default=None, help="One user (default: every wallet owner).")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        users = [args.user_id] if args.user_id else [
            int(u) for (u,) in db.execute(text("SELECT DISTINCT user_id FROM crypto_wallets WHERE user_id IS NOT NULL")).all()
        ]
        for user_id in users:
            r = run_backfill(db, user_id, apply=args.apply)
            print(
                f"user {user_id}: {r['items']} unpriced item(s) of tokens priced elsewhere; "
                f"{len(r['requests'])} request(s) this run (+{r['remaining_requests']} later); "
                f"{r['skipped_unknown_tokens']} item(s) of tokens no provider prices skipped"
            )
            for req in r["requests"]:
                print(f"  {req['date']}: {req['coins']} coin(s)")
            if args.apply:
                print(f"  {r['status']}: {r['items_priced']} item(s) priced, {r['failed_requests']} request(s) failed")
    finally:
        db.close()
    if not args.apply:
        print("Dry run: nothing fetched. APPLY=1 to fetch from DefiLlama.")


if __name__ == "__main__":
    main()
