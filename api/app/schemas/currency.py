from pydantic import BaseModel

class CurrencyCreate(BaseModel):
    code: str
    name: str | None = None

class CurrencyOut(BaseModel):
    id: int
    code: str
    name: str | None = None

    class Config:
        from_attributes = True
