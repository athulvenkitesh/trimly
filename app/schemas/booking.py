from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.models.booking import BookingStatus

class BookingCreate(BaseModel):
    shop_id: int
    service_id: int
    starts_at: datetime

class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shop_id: int
    service_id: int
    # Null for walk-ins, which have no customer account.
    customer_id: int | None = None
    starts_at: datetime
    ends_at: datetime
    status: BookingStatus
    code: str

class CustomerBookingOut(BookingOut):
    """Booking listed for the customer, enriched with display fields."""
    shop_name: str
    service_name: str
    payment_status: str | None = None
    amount_paise: int | None = None
    convenience_fee_paise: int | None = None

class PaymentStartOut(BaseModel):
    """Result of starting payment on a web booking.

    COMPLETED means the money is settled (mock/test provider);
    PENDING means the customer must follow checkout_url (UPI intent
    or a card payment link). `provider` names the backend used so the
    UI can flag an auto-completed mock instead of implying real money moved.
    """
    booking_id: int
    amount_paise: int
    convenience_fee_paise: int
    method: str
    payment_status: str
    checkout_url: str | None = None
    provider: str | None = None

class OwnerBookingOut(BaseModel):
    """Booking view for shop owners, enriched with display fields."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    starts_at: datetime
    ends_at: datetime
    status: BookingStatus
    code: str
    service_id: int
    service_name: str
    service_duration_minutes: int
    # Price of the booked service, so the owner overview can total the day's takings.
    service_price_paise: int = 0
    # Walk-ins have no account: customer_id/email are null and walk_in_name is set.
    customer_id: int | None = None
    customer_email: str | None = None
    walk_in_name: str | None = None
    is_walk_in: bool = False

class NextSlotOut(BaseModel):
    """The next moment a walk-in can be seated, measured from the current time."""
    shop_id: int
    is_open: bool
    service_id: int | None = None
    service_name: str | None = None
    duration_minutes: int | None = None
    starts_at: datetime | None = None
    # Why no start was found: "no_hours" (business hours never configured),
    # "fully_booked" (open hours exist but every slot is taken for 7 days), or null.
    reason: str | None = None

class WalkInCreate(BaseModel):
    """Seat a customer who walked in without booking, in the next free slot."""
    service_id: int | None = None
    name: str | None = Field(default=None, max_length=120)
    # The slot the owner is looking at; omitted -> the next free slot is chosen.
    starts_at: datetime | None = None
