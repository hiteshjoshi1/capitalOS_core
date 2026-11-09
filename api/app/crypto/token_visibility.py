"""Spam/unknown wallet tokens, hidden by default (#342, D-87).

Wallets pick up airdropped tokens nobody prices (on 2026-11-08 the real wallets held 173
such tokens, one an ERC-20 calling itself "SOL"). They are already worth 0 and, since
#331, add no quantity, but they crowd the crypto lists. A contract token is
**unknown** when:
- no snapshot of the user's own wallets has ever priced it (any date), and
- it isn't on the token allowlist (Settings → Admin, ``crypto_allowlist``).
Native coins and exchange balances (no contract) are never unknown.

A user can override per token (``crypto_token_visibility``, migration 083): ``shown``
("Not spam") or ``hidden`` ("Hide"); the override wins. Identity is chain plus contract
address, as #331's ``token_key`` (never the symbol alone). Valuation is unchanged: this
only decides what the lists show.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crypto.price_backfill import TokenKey, token_key

VISIBILITY_VALUES = ("shown", "hidden")


def contract_key(item: Dict[str, Any]) -> Optional[TokenKey]:
    """The token's key when it has a contract/mint; None for native coins and exchange balances."""
    if not str(item.get("contract_or_mint") or "").strip():
        return None
    return token_key(item)


def key_text(key: TokenKey) -> str:
    return f"{key[0]}:{key[1]}"


def _ever_priced(db: Session, current_user_id: int, keys: Set[TokenKey]) -> Set[TokenKey]:
    if not keys:
        return set()
    from app.crypto.valuation import wallet_scope_sql

    rows = db.execute(
        text(
            """
            SELECT DISTINCT i.chain, i.contract_or_mint
            FROM crypto_wallet_snapshot_items i
            JOIN crypto_wallet_snapshots s ON s.id = i.snapshot_id
            JOIN crypto_wallets w ON w.id = s.wallet_id
            WHERE i.price_usd IS NOT NULL
              AND i.contract_or_mint IS NOT NULL
              AND """
            + wallet_scope_sql("w")
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    priced = {token_key(dict(row)) for row in rows}
    return {key for key in keys if key in priced}


def _allowlisted(db: Session) -> Set[TokenKey]:
    rows = db.execute(text("SELECT chain, contract_address FROM crypto_allowlist")).mappings().all()
    out: Set[TokenKey] = set()
    for row in rows:
        key = token_key({"chain": row["chain"], "contract_or_mint": row["contract_address"]})
        if key is not None:
            out.add(key)
    return out


def overrides(db: Session, current_user_id: int) -> Dict[TokenKey, str]:
    rows = db.execute(
        text(
            "SELECT chain, contract_or_mint, visibility FROM crypto_token_visibility "
            "WHERE user_id = :u"
        ),
        {"u": current_user_id},
    ).mappings().all()
    out: Dict[TokenKey, str] = {}
    for row in rows:
        key = token_key({"chain": row["chain"], "contract_or_mint": row["contract_or_mint"]})
        if key is not None:
            out[key] = str(row["visibility"])
    return out


def annotate(db: Session, current_user_id: int, items: Iterable[Dict[str, Any]]) -> int:
    """Add ``token_key``, ``unknown_token``, ``visibility_override``, ``hidden`` and
    ``hidden_reason`` to each item (in place). Returns how many are hidden."""
    items = list(items)
    keys = {key for key in (contract_key(item) for item in items) if key is not None}
    priced_now = {contract_key(item) for item in items if item.get("price_usd") is not None}
    ever = _ever_priced(db, current_user_id, keys - priced_now) | (priced_now & keys)
    allowed = _allowlisted(db) if keys else set()
    chosen = overrides(db, current_user_id) if keys else {}
    hidden_count = 0
    for item in items:
        key = contract_key(item)
        item["token_key"] = key_text(key) if key is not None else None
        unknown = key is not None and key not in ever and key not in allowed
        override = chosen.get(key) if key is not None else None
        if override == "shown":
            hidden, reason = False, None
        elif override == "hidden":
            hidden, reason = True, "user_hidden"
        else:
            hidden, reason = unknown, ("unknown_token" if unknown else None)
        item["unknown_token"] = unknown
        item["visibility_override"] = override
        item["hidden"] = hidden
        item["hidden_reason"] = reason
        hidden_count += int(hidden)
    return hidden_count


def set_override(db: Session, current_user_id: int, chain: str, contract: str, visibility: Optional[str]) -> None:
    """Save "shown"/"hidden" for one token of this user; None clears it (back to automatic)."""
    key = token_key({"chain": chain, "contract_or_mint": contract})
    if key is None or not str(contract or "").strip():
        raise ValueError("chain and contract_or_mint are required")
    if visibility is not None and visibility not in VISIBILITY_VALUES:
        raise ValueError("visibility must be 'shown', 'hidden' or null")
    db.execute(
        text("DELETE FROM crypto_token_visibility WHERE user_id = :u AND chain = :c AND contract_or_mint = :t"),
        {"u": current_user_id, "c": key[0], "t": key[1]},
    )
    if visibility is not None:
        db.execute(
            text(
                "INSERT INTO crypto_token_visibility (user_id, chain, contract_or_mint, visibility) "
                "VALUES (:u, :c, :t, :v)"
            ),
            {"u": current_user_id, "c": key[0], "t": key[1], "v": visibility},
        )
    db.commit()


def list_overrides(db: Session, current_user_id: int) -> List[Dict[str, str]]:
    return [
        {"chain": key[0], "contract_or_mint": key[1], "visibility": value}
        for key, value in sorted(overrides(db, current_user_id).items())
    ]
