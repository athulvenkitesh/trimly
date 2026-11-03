from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import BusinessHours
from app.schemas.availability import AvailabilityOut
from app.services.availability_service import AvailabilityService

router = APIRouter(prefix="/shops/{shop_id}/availability", tags=["availability"])

@router.get("", response_model=AvailabilityOut, summary="Get bookable slots")
def availability(shop_id: int, service_id: int, date_: date = Query(alias="date"), db: Session = Depends(get_db)):
    slots = AvailabilityService(db).get_available_slots(shop_id, service_id, date_)
    reason: str | None = None
    if not slots:
        hours = db.scalars(select(BusinessHours).where(BusinessHours.shop_id == shop_id)).all()
        if not any(not h.is_closed for h in hours):
            # An unconfigured shop dead-ends the customer with no explanation otherwise.
            reason = "no_hours"
        elif not any(h.weekday == date_.weekday() and not h.is_closed for h in hours):
            reason = "closed_day"
        else:
            reason = "fully_booked"
    return AvailabilityOut(shop_id=shop_id, service_id=service_id, date=date_, slots=slots, reason=reason)
