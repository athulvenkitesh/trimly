from datetime import time
from pydantic import BaseModel, ConfigDict, Field, model_validator

class BusinessHoursUpsert(BaseModel):
    weekday: int = Field(ge=0, le=6)
    opens_at: time
    closes_at: time
    is_closed: bool = False

    @model_validator(mode="after")
    def close_after_open(self):
        if not self.is_closed and self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be after opens_at")
        return self

class BusinessHoursOut(BusinessHoursUpsert):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shop_id: int

class SlotSettingsUpdate(BaseModel):
    interval_minutes: int = Field(ge=5, le=120)

class SlotSettingsOut(SlotSettingsUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shop_id: int
