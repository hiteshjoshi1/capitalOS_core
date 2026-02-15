from pydantic import BaseModel

class AccountCreate(BaseModel):
    name: str
    platform_id: int | None = None
    platform: str  # keep for now to avoid blocking if platform_id isn't used yet
    account_type: str
    currency: str
    country: str | None = None

class AccountOut(BaseModel):
    id: int
    name: str
    platform: str
    platform_id: int | None = None
    account_type: str
    currency: str
    country: str | None = None

    class Config:
        from_attributes = True
