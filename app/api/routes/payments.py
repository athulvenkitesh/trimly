import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.integrations.webhook_signature import verify_hmac
from app.integrations.whatsapp import client
from app.models import Booking, Payment, PaymentStatus, Service, Shop
from app.services.whatsapp_flow import payment_confirmation_message

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/razorpay/webhook", summary="Confirm a Razorpay payment and lock in the booking")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if settings.payment_webhook_secret:
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not verify_hmac(body, signature, settings.payment_webhook_secret):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    payload = json.loads(body or b"{}")
    event = payload.get("event", "")
    if not event.startswith("payment_link."):
        return {"status": "ignored"}

    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    reference = entity.get("payment_link_id") or entity.get("payment_id")
    payment = db.scalar(select(Payment).where(Payment.provider_reference == reference)) if reference else None
    if not payment:
        return {"status": "ignored"}
    if payment.status == PaymentStatus.COMPLETED:
        return {"status": "already-completed"}

    if event == "payment_link.completed":
        payment.status = PaymentStatus.COMPLETED
        db.commit()
        booking = db.get(Booking, payment.booking_id)
        shop = db.get(Shop, booking.shop_id)
        service = db.get(Service, booking.service_id)
        # Best-effort notification; the payment itself is already settled.
        try:
            client.send_text(payment.customer_phone, payment_confirmation_message(booking, shop, service, payment))
        except Exception:
            pass
    elif event in ("payment_link.failed", "payment_link.expired"):
        payment.status = PaymentStatus.FAILED
        db.commit()
    return {"status": "processed"}


@router.get("/razorpay/callback", response_class=PlainTextResponse, summary="Landing page after a customer pays")
def razorpay_callback():
    return "Payment received. You can close this window — your booking is confirmed on WhatsApp."
