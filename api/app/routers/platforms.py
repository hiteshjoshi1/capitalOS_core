import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.auth_context import CurrentUser, account_scope_sql, require_admin, require_current_user
from app.db.session import get_db
from app.models.platform import Platform, PlatformType
from app.schemas.platform import PlatformCreate, PlatformOut

router = APIRouter(prefix="/platforms", tags=["platforms"], dependencies=[Depends(require_current_user)])

@router.get("", response_model=list[PlatformOut])
def list_platforms(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_current_user),
):
    return db.query(Platform).order_by(Platform.country, Platform.platform_type, Platform.code).all()

@router.get("/options")
def platform_options(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    # Only the caller's own accounts contribute countries (#153), like /accounts/options.
    q = text(f"""
        SELECT DISTINCT country FROM platforms WHERE country IS NOT NULL
        UNION
        SELECT DISTINCT a.country FROM accounts a
        WHERE a.country IS NOT NULL
          AND {account_scope_sql("a")}
        ORDER BY country
    """)
    countries = [r[0] for r in db.execute(q, {"current_user_id": current_user.id}).fetchall()]
    return {
        "platform_types": list(PlatformType.enums),
        "countries": countries,
        "country_pattern": "^[A-Z]{2,3}$",
    }

@router.post("", response_model=PlatformOut)
def create_platform(
    payload: PlatformCreate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    code = payload.code.strip().upper()
    name = payload.name.strip()
    platform_type = payload.platform_type.strip()
    country = payload.country.strip().upper()

    if not code or not name:
        raise HTTPException(status_code=400, detail="code and name are required")
    if platform_type not in PlatformType.enums:
        raise HTTPException(status_code=400, detail="invalid platform_type")
    if not re.match(r"^[A-Z0-9_]+$", code):
        raise HTTPException(status_code=400, detail="invalid code")
    if not re.match(r"^[A-Z]{2,3}$", country):
        raise HTTPException(status_code=400, detail="invalid country")

    existing = db.query(Platform).filter(Platform.code == code).one_or_none()
    if existing:
        return existing

    platform = Platform(
        code=code,
        name=name,
        platform_type=platform_type,
        country=country,
        website=payload.website,
    )
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform
