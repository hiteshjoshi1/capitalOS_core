import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.currency import Currency
from app.schemas.currency import CurrencyCreate, CurrencyOut

router = APIRouter(prefix="/currencies", tags=["currencies"])

@router.get("", response_model=list[CurrencyOut])
def list_currencies(db: Session = Depends(get_db)):
    return db.query(Currency).order_by(Currency.code).all()

@router.post("", response_model=CurrencyOut)
def create_currency(payload: CurrencyCreate, db: Session = Depends(get_db)):
    code = payload.code.strip().upper()
    name = payload.name.strip() if payload.name else None

    if not re.match(r"^[A-Z]{3}$", code):
        raise HTTPException(status_code=400, detail="invalid currency")

    existing = db.query(Currency).filter(Currency.code == code).one_or_none()
    if existing:
        return existing

    cur = Currency(code=code, name=name)
    db.add(cur)
    db.commit()
    db.refresh(cur)
    return cur
