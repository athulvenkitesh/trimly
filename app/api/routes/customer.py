from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.integrations.payments.provider import get_payment_provider
from app.models import Booking, Payment, PaymentStatus, Service, Shop, User
from app.schemas.booking import CustomerBookingOut, PaymentStartOut
from app.services.whatsapp_flow import rupees

router = APIRouter(prefix="/customer", tags=["customer"])


def enrich(db: Session, bookings: list[Booking]) -> list[CustomerBookingOut]:
    """Join shop/service names plus the latest payment for each booking."""
    out: list[CustomerBookingOut] = []
    for booking in bookings:
        shop = db.get(Shop, booking.shop_id)
        service = db.get(Service, booking.service_id)
        payment = db.scalar(select(Payment).where(Payment.booking_id == booking.id).order_by(Payment.id.desc()))
        out.append(CustomerBookingOut(
            id=booking.id, shop_id=booking.shop_id, service_id=booking.service_id,
            customer_id=booking.customer_id, starts_at=booking.starts_at, ends_at=booking.ends_at,
            status=booking.status, code=booking.code,
            shop_name=shop.name if shop else "—", service_name=service.name if service else "—",
            payment_status=payment.status.value if payment else None,
            amount_paise=payment.amount_paise if payment else None,
            convenience_fee_paise=payment.convenience_fee_paise if payment else None,
        ))
    return out


@router.get("/bookings", response_model=list[CustomerBookingOut], summary="My bookings, newest first")
def my_bookings(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    bookings = db.scalars(
        select(Booking).where(Booking.customer_id == user.id).order_by(Booking.starts_at.desc())
    ).all()
    return enrich(db, bookings)


@router.post("/bookings/{booking_id}/pay", response_model=PaymentStartOut, summary="Start payment for a booking (method=upi|card)")
def pay_booking(booking_id: int, method: str = "upi", user: User = Depends(require_customer), db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if not booking or booking.customer_id != user.id:
        raise HTTPException(404, "Booking not found")
    if booking.status != "CONFIRMED":  # enum value comparison via str
        raise HTTPException(409, "This booking is not active")
    existing = db.scalar(select(Payment).where(Payment.booking_id == booking.id, Payment.status == PaymentStatus.COMPLETED))
    if existing:
        raise HTTPException(409, "This booking is already paid")
    shop = db.get(Shop, booking.shop_id)
    service = db.get(Service, booking.service_id)
    fee = shop.convenience_fee_paise  # web bookings always show the shop's explicit fee
    if fee == 0:
        from app.core.config import settings

        fee = settings.default_convenience_fee_paise
    method = (method or "upi").lower()
    if method not in ("upi", "card"):
        raise HTTPException(422, "method must be 'upi' or 'card'")
    pending_same = db.scalar(select(Payment).where(
        Payment.booking_id == booking.id,
        Payment.status == PaymentStatus.PENDING,
        Payment.method == method))
    if pending_same:
        raise HTTPException(409, f"A {method} payment is already in progress for this booking")
    total = service.price_paise + fee
    provider = get_payment_provider(method)
    result = provider.create_payment(
        booking_id=booking.id, amount_paise=total,
        description=f"{service.name} at {shop.name}")
    status_label = "COMPLETED" if result.status == "COMPLETED" else "PENDING"
    db.add(Payment(
        booking_id=booking.id, customer_phone=user.phone or "web", provider=type(provider).__name__, method=method,
        provider_reference=result.provider_reference, amount_paise=total,
        convenience_fee_paise=fee,
        status=PaymentStatus.COMPLETED if result.status == "COMPLETED" else PaymentStatus.PENDING))
    db.commit()
    return PaymentStartOut(booking_id=booking.id, amount_paise=total, convenience_fee_paise=fee,
                           method=method, payment_status=status_label, checkout_url=result.checkout_url,
                           provider=type(provider).__name__)
