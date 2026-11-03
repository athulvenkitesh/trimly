from datetime import date, datetime, time, timedelta, timezone
from app.core.database import SessionLocal
from app.models import Booking, BusinessHours, Service, Shop, SlotSettings, User, UserRole
from app.core.security import hash_password
from app.services.booking_service import BookingService
from fastapi import HTTPException

def test_same_slot_can_only_be_reserved_once():
    db = SessionLocal()
    try:
        owner = User(email="owner@example.com", password_hash=hash_password("password123"), role=UserRole.SHOP_OWNER)
        customer_a = User(email="a@example.com", password_hash=hash_password("password123"), role=UserRole.CUSTOMER)
        customer_b = User(email="b@example.com", password_hash=hash_password("password123"), role=UserRole.CUSTOMER)
        db.add_all([owner, customer_a, customer_b]); db.commit()
        shop = Shop(owner_id=owner.id, name="Cut Here"); db.add(shop); db.commit()
        service = Service(shop_id=shop.id, name="Cut", duration_minutes=30); db.add(service)
        future = datetime.now(timezone.utc) + timedelta(days=2)
        db.add_all([SlotSettings(shop_id=shop.id, interval_minutes=30), BusinessHours(shop_id=shop.id, weekday=future.weekday(), opens_at=time(0, 0), closes_at=time(23, 59))]); db.commit()
        requested = future.replace(minute=(future.minute // 30) * 30, second=0, microsecond=0)
        first = BookingService(db).create_booking(customer_id=customer_a.id, shop_id=shop.id, service_id=service.id, starts_at=requested)
        assert first.id
        try:
            BookingService(db).create_booking(customer_id=customer_b.id, shop_id=shop.id, service_id=service.id, starts_at=requested)
            assert False, "Expected conflict"
        except HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail["error"]["code"] == "SLOT_NOT_AVAILABLE"
    finally:
        db.close()
