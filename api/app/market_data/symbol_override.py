"""Per-asset Yahoo symbol override (#222).

The quote refresh asks Yahoo for ``<ticker><exchange suffix>`` (``.NS`` on NSE).
A holding Yahoo lists under another suffix only (an Indian stock quoted on BSE
as ``<CODE>.BO``) needs ``market_symbol_map.yahoo_symbol_override``; a symbol
that already ends in a Yahoo market suffix is quoted as it is
(``YAHOO_QUALIFIED_SUFFIXES``). This sets or clears it for one asset on one
exchange, creating the map row when the refresh hasn't yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.market_data.service import _default_yahoo_symbol, _ticker_candidate


class SymbolOverrideError(ValueError):
    pass


@dataclass
class SymbolOverrideResult:
    applied: bool
    asset_id: int
    exchange_code: str
    action: str  # create_map | set | clear | unchanged
    before: str | None
    after: str | None
    quoted_as: str


def set_yahoo_symbol_override(
    db: Session,
    *,
    symbol: str,
    currency: str,
    exchange_code: str,
    yahoo_symbol: str | None,
    apply: bool,
) -> SymbolOverrideResult:
    """Set (``yahoo_symbol``) or clear (None) the override for the asset
    (``symbol``, ``currency``) on ``exchange_code``. Dry run unless ``apply``."""
    symbol = symbol.strip().upper()
    currency = currency.strip().upper()
    exchange_code = exchange_code.strip().upper()
    override = yahoo_symbol.strip().upper() if yahoo_symbol else None
    if override is not None and _ticker_candidate(override) is None:
        raise SymbolOverrideError(f"Not a ticker: {yahoo_symbol!r}")
    asset = db.execute(
        text("SELECT id FROM assets WHERE symbol = :symbol AND quote_currency = :currency"),
        {"symbol": symbol, "currency": currency},
    ).fetchone()
    if asset is None:
        raise SymbolOverrideError(f"No asset {symbol} in {currency}")
    asset_id = int(asset[0])
    existing = db.execute(
        text(
            """
            SELECT id, exchange_symbol, yahoo_symbol_override
            FROM market_symbol_map
            WHERE asset_id = :asset_id AND exchange_code = :exchange_code
            """
        ),
        {"asset_id": asset_id, "exchange_code": exchange_code},
    ).mappings().first()
    now = datetime.now(tz=timezone.utc)
    before = (existing["yahoo_symbol_override"] if existing else None) or None
    exchange_symbol = str(existing["exchange_symbol"]) if existing else symbol
    if existing is None:
        if override is None:
            action = "unchanged"
        else:
            action = "create_map"
            if apply:
                db.execute(
                    text(
                        """
                        INSERT INTO market_symbol_map
                          (asset_id, exchange_code, exchange_symbol, quote_currency, is_active,
                           yahoo_symbol_override, created_at, updated_at)
                        VALUES
                          (:asset_id, :exchange_code, :exchange_symbol, :currency, TRUE, :override, :now, :now)
                        """
                    ),
                    {
                        "asset_id": asset_id,
                        "exchange_code": exchange_code,
                        "exchange_symbol": symbol,
                        "currency": currency,
                        "override": override,
                        "now": now,
                    },
                )
    elif (before or None) == override:
        action = "unchanged"
    else:
        action = "set" if override else "clear"
        if apply:
            db.execute(
                text(
                    "UPDATE market_symbol_map SET yahoo_symbol_override = :override, updated_at = :now WHERE id = :id"
                ),
                {"override": override, "now": now, "id": int(existing["id"])},
            )
    if apply:
        db.commit()
    else:
        db.rollback()
    return SymbolOverrideResult(
        applied=apply,
        asset_id=asset_id,
        exchange_code=exchange_code,
        action=action,
        before=before,
        after=override,
        quoted_as=_default_yahoo_symbol(override or exchange_symbol, exchange_code),
    )
