from datetime import date, datetime
from pydantic import BaseModel

class AvailabilityOut(BaseModel):
    shop_id: int
    service_id: int
    date: date
    slots: list[datetime]
    # Why `slots` is empty: "no_hours" (the shop never set business hours),
    # "closed_day" (closed on this weekday), "fully_booked" (open but all taken),
    # or null when slots exist. Lets the customer UI explain instead of dead-ending.
    reason: str | None = None
