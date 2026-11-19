from pydantic import BaseModel, ConfigDict

class PlatformCreate(BaseModel):
    code: str
    name: str
    platform_type: str
    country: str
    website: str | None = None

class PlatformOut(BaseModel):
    id: int
    code: str
    name: str
    platform_type: str
    country: str
    website: str | None = None

    model_config = ConfigDict(from_attributes=True)
