"""Source freshness (#252, D-67): the Data Hub's per-source table and the
Overview's overdue line read GET /dashboard/source-freshness (one lean endpoint,
D-57). A user sets a source's expected cadence with PUT and resets it with DELETE."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import get_db
from app.schemas.source_freshness import SourceFreshnessOverrideIn, SourceFreshnessResponse, SourceFreshnessRow
from app.services import source_freshness as svc

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_current_user)])


@router.get("/source-freshness", response_model=SourceFreshnessResponse)
def get_source_freshness(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """One row per data source (accounts, wallets, quote feeds, FX): newest data
    date, expected cadence, overdue and by how long. Overdue rows first."""
    return svc.source_freshness(db, current_user.id)


@router.put("/source-freshness/{source_key}", response_model=SourceFreshnessRow)
def put_source_freshness_override(
    source_key: str,
    payload: SourceFreshnessOverrideIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Set the expected cadence of one of your sources (404 for any other key)."""
    try:
        return svc.set_override(db, current_user.id, source_key, payload.cadence, payload.grace_days)
    except svc.UnknownSource:
        raise HTTPException(status_code=404, detail="source not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/source-freshness/{source_key}", response_model=SourceFreshnessRow)
def delete_source_freshness_override(
    source_key: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Back to the source type's default cadence."""
    try:
        return svc.clear_override(db, current_user.id, source_key)
    except svc.UnknownSource:
        raise HTTPException(status_code=404, detail="source not found")
