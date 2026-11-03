from datetime import datetime
from pydantic import BaseModel, Field

class AdminShopOut(BaseModel):
    id: int
    name: str
    address: str | None
    is_active: bool
    owner_email: str
    service_count: int
    created_at: datetime

class AdminShopStatusUpdate(BaseModel):
    is_active: bool

class AdminServiceOut(BaseModel):
    id: int
    name: str
    duration_minutes: int
    price_paise: int
    is_active: bool
    shop_id: int
    shop_name: str
