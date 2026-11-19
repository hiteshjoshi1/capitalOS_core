from pydantic import BaseModel, ConfigDict

class CurrencyCreate(BaseModel):
    code: str
    name: str | None = None
    country: str | None = None

class CurrencyOut(BaseModel):
    id: int
    code: str
    name: str | None = None
    country: str | None = None

    model_config = ConfigDict(from_attributes=True)
