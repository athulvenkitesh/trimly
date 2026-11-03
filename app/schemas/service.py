from pydantic import BaseModel, ConfigDict, Field

class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    duration_minutes: int = Field(ge=5, le=480)
    price_paise: int = Field(default=0, ge=0)

class ServiceOut(ServiceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shop_id: int
    is_active: bool
