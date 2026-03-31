import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import get_db
from app.models.currency import Currency
from app.schemas.currency import CurrencyCreate, CurrencyOut

router = APIRouter(prefix="/currencies", tags=["currencies"], dependencies=[Depends(require_current_user)])

@router.get("", response_model=list[CurrencyOut])
def list_currencies(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_current_user),
):
    return db.query(Currency).order_by(Currency.code).all()

@router.post("", response_model=CurrencyOut)
def create_currency(
    payload: CurrencyCreate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_current_user),
):
    code = payload.code.strip().upper()
    name = payload.name.strip() if payload.name else None
    country = payload.country.strip() if payload.country else None

    if not re.match(r"^[A-Z]{3}$", code):
        raise HTTPException(status_code=400, detail="invalid currency")

    existing = db.query(Currency).filter(Currency.code == code).one_or_none()
    if existing:
        return existing

    cur = Currency(code=code, name=name, country=country)
    db.add(cur)
    db.commit()
    db.refresh(cur)
    return cur
