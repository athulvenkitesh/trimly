from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Booking, BookingStatus, BusinessHours, Service, Shop, SlotSettings

class AvailabilityService:
    """The single source of truth for publicly bookable start times."""
    def __init__(self, db: Session):
        self.db = db

    def get_available_slots(self, shop_id: int, service_id: int, day: date) -> list[datetime]:
        shop = self.db.get(Shop, shop_id)
        service = self.db.get(Service, service_id)
        if not shop or not shop.is_active or not service or service.shop_id != shop_id or not service.is_active:
            return []
        hours = self.db.scalar(select(BusinessHours).where(BusinessHours.shop_id == shop_id, BusinessHours.weekday == day.weekday()))
        if not hours or hours.is_closed:
            return []
        interval = shop.slot_settings.interval_minutes if shop.slot_settings else 30
        tz = timezone.utc
        opening = datetime.combine(day, hours.opens_at, tzinfo=tz)
        closing = datetime.combine(day, hours.closes_at, tzinfo=tz)
        bookings = self.db.scalars(select(Booking).where(Booking.shop_id == shop_id, Booking.status == BookingStatus.CONFIRMED, Booking.starts_at >= opening, Booking.starts_at < closing)).all()
        occupied = {self._aware(booking.starts_at) for booking in bookings}
        now = datetime.now(tz)
        slots: list[datetime] = []
        cursor = opening
        while cursor + timedelta(minutes=service.duration_minutes) <= closing:
            if cursor > now and cursor not in occupied:
                slots.append(cursor)
            cursor += timedelta(minutes=interval)
        return slots

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
