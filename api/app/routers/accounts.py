from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountOut

router = APIRouter(prefix="/accounts", tags=["accounts"])

@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return db.query(Account).order_by(Account.id).all()

@router.post("", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    # lightweight validation
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name is required")

    acc = Account(
        name=payload.name.strip(),
        platform=payload.platform.strip(),
        platform_id=payload.platform_id,
        account_type=payload.account_type,
        currency=payload.currency,
        country=payload.country,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc
