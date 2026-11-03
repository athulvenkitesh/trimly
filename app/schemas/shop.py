from datetime import datetime
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, model_validator

class ShopLocationUpdate(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    place_id: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=20, pattern=r"^[A-Za-z0-9 \\\\-]{2,20}$")
    address: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_coordinates(self):
        if self.latitude is not None and self.longitude is None:
            raise ValueError("longitude is required when latitude is set")
        if self.longitude is not None and self.latitude is None:
            raise ValueError("latitude is required when longitude is set")
        if self.latitude is not None and not (isfinite(self.latitude) and isfinite(self.longitude)):
            raise ValueError("latitude and longitude must be finite numbers")
        return self

class ShopLocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    latitude: float | None
    longitude: float | None
    place_id: str | None
    postal_code: str | None
    address: str | None

class ConvenienceFeeUpdate(BaseModel):
    convenience_fee_paise: int = Field(ge=0, le=1_000_000)

class ConvenienceFeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    shop_id: int
    convenience_fee_paise: int

class ShopCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    address: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    place_id: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=20, pattern=r"^[A-Za-z0-9 \\\\-]{2,20}$")

class ShopOut(ShopCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    is_active: bool
    created_at: datetime
    # Convenience fee customers pay on top of service prices (WhatsApp + web).
    convenience_fee_paise: int = 0
    # Round shop avatar on the customer map / shop pages; null -> initial-letter fallback.
    logo_url: str | None = None

class ShopSearchOut(ShopOut):
    """Shop result for customer discovery; distance only when coordinates supplied."""
    distance_km: float | None = None

class ShopStatusUpdate(BaseModel):
    """Open or close the shop for new bookings."""
    is_open: bool

class ShopStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    shop_id: int
    is_open: bool
