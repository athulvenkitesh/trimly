from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models import Booking, BookingStatus, BusinessHours, Service, Shop

SLOT_STEP_MINUTES = 5
from app.services.availability_service import AvailabilityService
from app.services.booking_code_service import BookingCodeService

class BookingService:
    def __init__(self, db: Session):
        self.db = db
        self.availability = AvailabilityService(db)
        self.codes = BookingCodeService()

    def create_booking(self, *, customer_id: int, shop_id: int, service_id: int, starts_at: datetime) -> Booking:
        starts_at = starts_at.astimezone(timezone.utc) if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
        try:
            # Lock the shop row so competing flows serialize their availability check.
            # The partial unique index remains the authoritative protection across workers.
            shop = self.db.scalar(select(Shop).where(Shop.id == shop_id).with_for_update())
            service = self.db.get(Service, service_id)
            if not shop or not service or service.shop_id != shop_id:
                raise HTTPException(404, "Shop or service not found")
            available = self.availability.get_available_slots(shop_id, service_id, starts_at.date())
            if starts_at not in available:
                raise self._slot_conflict()
            booking = Booking(shop_id=shop_id, service_id=service_id, customer_id=customer_id,
                              starts_at=starts_at, ends_at=starts_at + timedelta(minutes=service.duration_minutes),
                              code=self.codes.new_code())
            self.db.add(booking)
            self.db.commit()
            self.db.refresh(booking)
            return booking
        except IntegrityError as exc:
            self.db.rollback()
            raise self._slot_conflict() from exc

    def next_available_slot(self, shop_id: int, service_id: int, days: int = 7) -> datetime | None:
        """The first bookable start time on the shop's slot grid, looking up to `days` ahead."""
        today = datetime.now(timezone.utc).date()
        for offset in range(days):
            slots = self.availability.get_available_slots(shop_id, service_id, today + timedelta(days=offset))
            if slots:
                return slots[0]
        return None

    def has_open_hours(self, shop_id: int) -> bool:
        """True when at least one weekday is open (is_closed=False), regardless of window."""
        return self.db.scalar(select(BusinessHours).where(
            BusinessHours.shop_id == shop_id, BusinessHours.is_closed.is_(False)).limit(1)) is not None

    def day_bounds(self, shop_id: int, day: date) -> tuple[datetime, datetime] | None:
        hours = self.db.scalar(select(BusinessHours).where(
            BusinessHours.shop_id == shop_id, BusinessHours.weekday == day.weekday()))
        if not hours or hours.is_closed:
            return None
        return (datetime.combine(day, hours.opens_at, tzinfo=timezone.utc),
                datetime.combine(day, hours.closes_at, tzinfo=timezone.utc))

    def overlaps(self, shop_id: int, starts_at: datetime, ends_at: datetime) -> bool:
        """True when any confirmed booking at the shop intersects [starts_at, ends_at)."""
        return self.db.scalar(select(Booking).where(
            Booking.shop_id == shop_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at < ends_at,
            Booking.ends_at > starts_at,
        ).limit(1)) is not None

    def is_within_hours(self, shop_id: int, starts_at: datetime, ends_at: datetime) -> bool:
        bounds = self.day_bounds(shop_id, starts_at.date())
        return bool(bounds and bounds[0] <= starts_at and ends_at <= bounds[1])

    def next_free_start(self, shop_id: int, service_id: int, after: datetime | None = None, days: int = 7) -> datetime | None:
        """The soonest moment a walk-in can be seated, starting from `after` (default: now).

        Unlike the public grid this starts at the current time (rounded up to the
        next 5 minutes) and steps in 5-minute increments, so the owner can push
        the start later in small blocks without leaving gaps in the calendar.
        """
        service = self.db.get(Service, service_id)
        if not service:
            return None
        duration = timedelta(minutes=service.duration_minutes)
        after = after or datetime.now(timezone.utc)
        after = after.astimezone(timezone.utc) if after.tzinfo else after.replace(tzinfo=timezone.utc)
        # Owners can hand-pick a start time; a moment in the past means "from now".
        after = max(after, datetime.now(timezone.utc))
        after = after.replace(second=0, microsecond=0)
        remainder = after.minute % SLOT_STEP_MINUTES
        if remainder:
            after += timedelta(minutes=SLOT_STEP_MINUTES - remainder)
        for offset in range(days):
            day = (after + timedelta(days=offset)).date()
            bounds = self.day_bounds(shop_id, day)
            if not bounds:
                continue
            opening, closing = bounds
            cursor = max(opening, after)
            while cursor + duration <= closing:
                if not self.overlaps(shop_id, cursor, cursor + duration):
                    return cursor
                cursor += timedelta(minutes=SLOT_STEP_MINUTES)
        return None

    def create_walk_in(self, *, shop_id: int, service_id: int | None = None, name: str | None = None,
                       starts_at: datetime | None = None) -> Booking:
        """Seat a walk-in customer in the next free slot.

        The booking is the same row a web booking produces minus the customer
        account, so the slot disappears from availability and the owner's
        "next available slot" moves forward.
        """
        try:
            shop = self.db.scalar(select(Shop).where(Shop.id == shop_id).with_for_update())
            if not shop:
                raise HTTPException(404, "Shop not found")
            if not shop.is_active:
                raise HTTPException(409, "Open your shop before seating walk-ins.")
            service = self.db.get(Service, service_id) if service_id else self.db.scalar(
                select(Service).where(Service.shop_id == shop_id, Service.is_active.is_(True)).order_by(Service.duration_minutes)
            )
            if not service or service.shop_id != shop_id or not service.is_active:
                raise HTTPException(404, "Service not found")
            if starts_at is not None:
                # Honour the moment the owner picked, as long as it is inside opening
                # hours and does not collide with an existing booking. Walk-ins may
                # start off-grid (a customer walks in at 10:47, not at 11:00).
                starts_at = starts_at.astimezone(timezone.utc) if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
                ends_at = starts_at + timedelta(minutes=service.duration_minutes)
                if not self.is_within_hours(shop_id, starts_at, ends_at):
                    raise HTTPException(409, "That time is outside your opening hours.")
                if self.overlaps(shop_id, starts_at, ends_at):
                    raise self._slot_conflict()
            else:
                starts_at = self.next_free_start(shop_id, service.id)
                if starts_at is None:
                    if not self.has_open_hours(shop_id):
                        raise HTTPException(409, "Set your business hours in Settings before seating walk-ins.")
                    raise HTTPException(409, "No free time in the next 7 days.")
            booking = Booking(
                shop_id=shop_id, service_id=service.id, customer_id=None,
                walk_in_name=(name or "").strip() or "Walk-in customer",
                starts_at=starts_at, ends_at=starts_at + timedelta(minutes=service.duration_minutes),
                code=self.codes.new_code(),
            )
            self.db.add(booking)
            self.db.commit()
            self.db.refresh(booking)
            return booking
        except IntegrityError as exc:
            self.db.rollback()
            raise self._slot_conflict() from exc

    def cancel_booking(self, booking_id: int, customer_id: int) -> Booking:
        booking = self.db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
        if not booking:
            raise HTTPException(404, "Booking not found")
        if booking.customer_id != customer_id:
            raise HTTPException(403, "Cannot cancel another customer's booking")
        if booking.status == BookingStatus.CANCELLED:
            return booking
        booking.status = BookingStatus.CANCELLED
        self.db.commit()
        return booking

    @staticmethod
    def _slot_conflict() -> HTTPException:
        return HTTPException(status_code=409, detail={"success": False, "error": {"code": "SLOT_NOT_AVAILABLE", "message": "The selected slot is no longer available."}})
