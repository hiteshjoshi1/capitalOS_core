import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.account import Account, AccountType
from app.models.currency import Currency
from app.models.platform import Platform
from app.schemas.account import AccountCreate, AccountOut

router = APIRouter(prefix="/accounts", tags=["accounts"])

@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return db.query(Account).order_by(Account.id).all()

@router.get("/options")
def account_options(db: Session = Depends(get_db)):
    account_types = list(AccountType.enums)

    q = text("""
        SELECT DISTINCT code AS currency FROM currencies WHERE code IS NOT NULL
        UNION
        SELECT DISTINCT currency FROM accounts WHERE currency IS NOT NULL
        UNION
        SELECT DISTINCT currency FROM transactions WHERE currency IS NOT NULL
        UNION
        SELECT DISTINCT currency FROM prices WHERE currency IS NOT NULL
        ORDER BY currency
    """)
    currencies = [r[0] for r in db.execute(q).fetchall()]

    q = text("""
        SELECT DISTINCT country FROM platforms WHERE country IS NOT NULL
        UNION
        SELECT DISTINCT country FROM accounts WHERE country IS NOT NULL
        ORDER BY country
    """)
    countries = [r[0] for r in db.execute(q).fetchall()]

    return {
        "account_types": account_types,
        "currencies": currencies,
        "countries": countries,
        "currency_pattern": "^[A-Z]{3}$",
    }

@router.post("", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
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
    country = payload.country
    if payload.platform_id is not None:
        platform = db.query(Platform).filter(Platform.id == payload.platform_id).one_or_none()
        if platform is None:
            raise HTTPException(status_code=400, detail="platform_id not found")
        platform_code = platform.code
        country = platform.country
    else:
        if not platform_code:
            raise HTTPException(status_code=400, detail="platform is required")
        platform = db.query(Platform).filter(Platform.code == platform_code).one_or_none()
        if platform is None:
            raise HTTPException(status_code=400, detail="platform not found")
        country = platform.country

    acc = Account(
        name=payload.name.strip(),
        platform=platform_code,
        platform_id=payload.platform_id,
        account_type=account_type,
        currency=currency,
        country=country,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc
