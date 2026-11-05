from datetime import date

from pydantic import BaseModel

class AccountCreate(BaseModel):
    name: str
    platform_id: int | None = None
    platform: str  # keep for now to avoid blocking if platform_id isn't used yet
    account_type: str
    currency: str
    country: str | None = None


class AccountUpdate(BaseModel):
    """PATCH /accounts/{id}: only the fields sent change (#207).

    closed_on: the date the account was closed (it counts up to that date and
    contributes nothing after it), or null to reopen it."""
    closed_on: date | None = None


class AccountOut(BaseModel):
    id: int
    name: str
    platform: str
    platform_id: int | None = None
    account_type: str
    currency: str
    country: str | None = None
    # Added by #207 (add-only).
    closed_on: date | None = None
    # The month the two fields below describe (YYYY-MM): the latest completed
    # month unless ?month= asks for another.
    data_month: str | None = None
    # Date of the newest fact that month's valuation reads for this account.
    last_data_as_of: str | None = None
    # Set when that fact is dated before the month began: the month shows a
    # value carried forward from that date.
    carried_forward_from: str | None = None

    class Config:
        from_attributes = True
