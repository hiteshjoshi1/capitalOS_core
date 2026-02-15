from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.platform import Platform
from app.schemas.platform import PlatformOut

router = APIRouter(prefix="/platforms", tags=["platforms"])

@router.get("", response_model=list[PlatformOut])
def list_platforms(db: Session = Depends(get_db)):
    return db.query(Platform).order_by(Platform.country, Platform.platform_type, Platform.code).all()
