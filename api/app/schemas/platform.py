from pydantic import BaseModel

class PlatformOut(BaseModel):
    id: int
    code: str
    name: str
    platform_type: str
    country: str
    website: str | None = None

    class Config:
        from_attributes = True
