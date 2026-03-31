from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class OwnershipReassignResult:
    accounts_updated: int
    wallets_updated: int
    crypto_networth_updated: int


def preview_unowned_counts(db: Session) -> OwnershipReassignResult:
    accounts = db.execute(text("SELECT COUNT(*) FROM accounts WHERE user_id IS NULL")).scalar_one()
    wallets = db.execute(text("SELECT COUNT(*) FROM crypto_wallets WHERE user_id IS NULL")).scalar_one()
    networth = db.execute(text("SELECT COUNT(*) FROM crypto_user_networth WHERE user_id IS NULL")).scalar_one()
    return OwnershipReassignResult(
        accounts_updated=int(accounts or 0),
        wallets_updated=int(wallets or 0),
        crypto_networth_updated=int(networth or 0),
    )


def reassign_legacy_ownership(db: Session, *, target_user_id: int, dry_run: bool = True) -> OwnershipReassignResult:
    user = db.execute(
        text("SELECT id, username FROM users WHERE id = :id LIMIT 1"),
        {"id": target_user_id},
    ).mappings().one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="target user not found")

    preview = preview_unowned_counts(db)
    if dry_run:
        return preview

    accounts_updated = db.execute(
        text(
            """
            UPDATE accounts
            SET user_id = :target_user_id
            WHERE user_id IS NULL
            """
        ),
        {"target_user_id": target_user_id},
    ).rowcount or 0

    wallets_updated = db.execute(
        text(
            """
            UPDATE crypto_wallets
            SET user_id = :target_user_id
            WHERE user_id IS NULL
            """
        ),
        {"target_user_id": target_user_id},
    ).rowcount or 0

    networth_updated = db.execute(
        text(
            """
            UPDATE crypto_user_networth
            SET user_id = :target_user_id
            WHERE user_id IS NULL
            """
        ),
        {"target_user_id": target_user_id},
    ).rowcount or 0

    db.commit()
    return OwnershipReassignResult(
        accounts_updated=int(accounts_updated),
        wallets_updated=int(wallets_updated),
        crypto_networth_updated=int(networth_updated),
    )

