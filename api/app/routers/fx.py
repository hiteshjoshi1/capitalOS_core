"""FX back-fill (#290): what's missing for the caller's data, and fetching it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_admin, require_current_user
from app.core.job_runs import TRIGGER_MANUAL
from app.db.session import get_db
from app.fx_backfill import plan_backfill, run_backfill

router = APIRouter(prefix="/fx", tags=["fx"], dependencies=[Depends(require_current_user)])


@router.get("/backfill-plan")
def fx_backfill_plan(
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """The span of the caller's data, its currencies, and the provider requests a
    back-fill would make (none when every weekday is covered). Reads only."""
    return plan_backfill(db, current_user.id, base_currency).as_dict()


@router.post("/backfill")
def fx_backfill_run(
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    """Fetch the missing past rates for the caller's data into the shared table
    (admin only: shared data, #152). Capped per run; run again to continue."""
    return run_backfill(db, current_user.id, base_currency, trigger=TRIGGER_MANUAL)
