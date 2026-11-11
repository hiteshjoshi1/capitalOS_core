import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.auth_context import CurrentUser, allow_legacy_null_ownership, require_current_user
from app.db.session import get_db
from app.models.account import Account, AccountType
from app.models.currency import Currency
from app.models.platform import Platform
from app.schemas.account import AccountCreate, AccountOut, AccountUpdate
from app.valuation import clock
from app.valuation.account_status import account_data_status
from app.wealth_rollup_dirty import mark_rollups_dirty

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(require_current_user)])

def _account_out(account: Account, status: dict[str, Any] | None, data_month: str | None) -> dict[str, Any]:
    out = AccountOut.model_validate(account).model_dump()
    out["data_month"] = data_month
    out["last_data_as_of"] = (status or {}).get("last_data_as_of")
    out["carried_forward_from"] = (status or {}).get("carried_forward_from")
    return out


def _data_status(db: Session, user_id: int, month: str | None) -> tuple[dict[int, dict[str, Any]], str]:
    """Per-account data status for ``month`` (default: the latest completed month)."""
    if month:
        month_start = clock._parse_month(month)
    else:
        month_start = clock._latest_completed_month_start(clock._current_anchor_ts())
    anchor_ts, _live = clock._effective_anchor_for_month(month_start)
    status = account_data_status(
        db, current_user_id=user_id, anchor_ts=anchor_ts, month_start=month_start.date()
    )
    return status, month_start.strftime("%Y-%m")


@router.get("", response_model=list[AccountOut])
def list_accounts(
    month: str | None = Query(
        None,
        description="YYYY-MM: the month whose data dates (last_data_as_of, carried_forward_from) "
        "are reported; default the latest completed month (#207).",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    query = db.query(Account)
    if allow_legacy_null_ownership():
        query = query.filter(or_(Account.user_id == current_user.id, Account.user_id.is_(None)))
    else:
        query = query.filter(Account.user_id == current_user.id)
    accounts = query.order_by(Account.id).all()
    status, data_month = _data_status(db, current_user.id, month)
    return [_account_out(account, status.get(int(account.id)), data_month) for account in accounts]


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Close an account on a date, or reopen it (``closed_on: null``) (#207).

    A closed account counts at every anchor on or before ``closed_on`` and
    contributes nothing after it. Only the account's owner may change it.
    History is marked dirty from the earlier of the old and new date (D-29)."""
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == current_user.id)
        .one_or_none()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    if "closed_on" not in payload.model_fields_set:
        raise HTTPException(status_code=422, detail="nothing to change: send closed_on (a date, or null to reopen)")
    new_closed_on = payload.closed_on
    if new_closed_on is not None and new_closed_on > clock._app_today():
        raise HTTPException(status_code=422, detail="closed_on can't be in the future")
    old_closed_on: date | None = account.closed_on
    if new_closed_on != old_closed_on:
        account.closed_on = new_closed_on
        changed_from = min(d for d in (old_closed_on, new_closed_on) if d is not None)
        mark_rollups_dirty(db, changed_from, account_id=int(account.id), reason="account_closed_on")
        db.add(account)
        db.commit()
        db.refresh(account)
    status, data_month = _data_status(db, current_user.id, None)
    return _account_out(account, status.get(int(account.id)), data_month)


@router.get("/options")
def account_options(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    account_types = list(AccountType.enums)

    q = text("""
        SELECT DISTINCT code AS currency FROM currencies WHERE code IS NOT NULL
        ORDER BY currency
    """)
    currencies = [r[0] for r in db.execute(q).fetchall()]

    country_owner_clause = "user_id = :current_user_id"
    if allow_legacy_null_ownership():
        country_owner_clause = "(user_id = :current_user_id OR user_id IS NULL)"
    q = text(f"""
        SELECT DISTINCT country FROM platforms WHERE country IS NOT NULL
        UNION
        SELECT DISTINCT country FROM accounts
        WHERE country IS NOT NULL
          AND {country_owner_clause}
        ORDER BY country
    """)
    countries = [r[0] for r in db.execute(q, {"current_user_id": current_user.id}).fetchall()]

    return {
        "account_types": account_types,
        "currencies": currencies,
        "countries": countries,
        "currency_pattern": "^[A-Z]{3}$",
    }

@router.post("", response_model=AccountOut)
def create_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    # lightweight validation
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="name is required")

    account_type = payload.account_type.strip()
    if account_type not in AccountType.enums:
        raise HTTPException(status_code=422, detail="invalid account_type")

    currency = payload.currency.strip().upper()
    if not re.match(r"^[A-Z]{3}$", currency):
        raise HTTPException(status_code=422, detail="invalid currency")

    existing_currency = db.query(Currency).filter(Currency.code == currency).one_or_none()
    if existing_currency is None:
        db.add(Currency(code=currency))
        db.flush()

    platform_code = payload.platform.strip()
    country = payload.country.strip().upper() if payload.country and payload.country.strip() else None
    if country is not None and not re.match(r"^[A-Z]{2,3}$", country):
        raise HTTPException(status_code=422, detail="invalid country")

    if payload.platform_id is not None:
        platform = db.query(Platform).filter(Platform.id == payload.platform_id).one_or_none()
        if platform is None:
            raise HTTPException(status_code=400, detail="platform_id not found")
        platform_code = platform.code
    else:
        if not platform_code:
            raise HTTPException(status_code=422, detail="platform is required")
        platform = db.query(Platform).filter(Platform.code == platform_code).one_or_none()
        if platform is None:
            raise HTTPException(status_code=400, detail="platform not found")

    country = country or platform.country

    acc = Account(
        name=payload.name.strip(),
        platform=platform_code,
        platform_id=payload.platform_id,
        user_id=current_user.id,
        account_type=account_type,
        currency=currency,
        country=country,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc
