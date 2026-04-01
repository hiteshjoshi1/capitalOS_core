import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.auth_context import CurrentUser, allow_legacy_null_ownership, require_current_user
from app.db.session import get_db
from app.models.account import Account, AccountType
from app.models.currency import Currency
from app.models.platform import Platform
from app.schemas.account import AccountCreate, AccountOut

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(require_current_user)])

@router.get("", response_model=list[AccountOut])
def list_accounts(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    query = db.query(Account)
    if allow_legacy_null_ownership():
        query = query.filter(or_(Account.user_id == current_user.id, Account.user_id.is_(None)))
    else:
        query = query.filter(Account.user_id == current_user.id)
    return query.order_by(Account.id).all()

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
        raise HTTPException(status_code=400, detail="name is required")

    account_type = payload.account_type.strip()
    if account_type not in AccountType.enums:
        raise HTTPException(status_code=400, detail="invalid account_type")

    currency = payload.currency.strip().upper()
    if not re.match(r"^[A-Z]{3}$", currency):
        raise HTTPException(status_code=400, detail="invalid currency")

    existing_currency = db.query(Currency).filter(Currency.code == currency).one_or_none()
    if existing_currency is None:
        db.add(Currency(code=currency))
        db.flush()

    platform_code = payload.platform.strip()
    country = payload.country.strip().upper() if payload.country and payload.country.strip() else None
    if country is not None and not re.match(r"^[A-Z]{2,3}$", country):
        raise HTTPException(status_code=400, detail="invalid country")

    if payload.platform_id is not None:
        platform = db.query(Platform).filter(Platform.id == payload.platform_id).one_or_none()
        if platform is None:
            raise HTTPException(status_code=400, detail="platform_id not found")
        platform_code = platform.code
    else:
        if not platform_code:
            raise HTTPException(status_code=400, detail="platform is required")
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
