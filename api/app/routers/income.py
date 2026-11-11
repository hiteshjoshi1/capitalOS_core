"""Income (#267): dividends plus interest, led by the year-on-year and trailing-12 totals."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import get_db
from app.fx import fx_status
from app.portfolio.income import income_summary
from app.schemas.income import IncomeSummaryOut
from app.valuation import clock

router = APIRouter(prefix="/income", tags=["income"], dependencies=[Depends(require_current_user)])


@router.get("/summary", response_model=IncomeSummaryOut)
def get_income_summary(
    month: str | None = Query(None, description="YYYY-MM (default: the current month)"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    if month is None:
        month = clock._app_today().strftime("%Y-%m")
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    return IncomeSummaryOut(**income_summary(db, current_user.id, month, base_currency.upper()), **fx_status())
