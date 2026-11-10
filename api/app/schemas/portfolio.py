"""Response models for the IBKR Flex GET routes (#361), same JSON as before."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class IbkrFlexImportRunOut(BaseModel):
    id: int
    status: Optional[str] = None
    legacy_account_id: Optional[int] = None
    report_date_from: Optional[str] = None
    report_date_to: Optional[str] = None
    requested_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class IbkrFlexReconciliationOut(BaseModel):
    id: int
    legacy_account_id: Optional[int] = None
    import_run_id: int
    report_date: Optional[str] = None
    reconciliation_type: Optional[str] = None
    expected_amount: float
    actual_amount: float
    difference_amount: float
    tolerance_amount: float
    status: Optional[str] = None


class IbkrFlexDataQualityEventOut(BaseModel):
    id: int
    legacy_account_id: Optional[int] = None
    import_run_id: Optional[int] = None
    report_date: Optional[str] = None
    severity: Optional[str] = None
    event_code: Optional[str] = None
    message: Optional[str] = None
    created_at: Optional[str] = None
