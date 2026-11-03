"""WhatsApp chat booking flow.

Customers message the business number and are walked through:
location/pincode -> nearby shops -> service -> time slot -> payment
(includes the configurable convenience fee).  Session state lives in
WhatsAppSession keyed by the customer's phone number.
"""
import re
import secrets
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.integrations.payments.provider import get_payment_provider
from app.models import (
    Booking, Payment, PaymentStatus, Service, Shop, User, UserRole, WhatsAppSession,
)
from app.services.availability_service import AvailabilityService
from app.services.booking_service import BookingService

RESTART_WORDS = {"hi", "hello", "hey", "start", "menu", "book"}
CANCEL_WORDS = {"0", "no", "cancel", "stop"}
CONFIRM_WORDS = {"1", "yes", "y", "confirm", "pay"}
# A customer marking a direct UPI payment as done while at the confirm step.
CLAIM_WORDS = {"paid", "done", "i paid", "payment done"}
PINCODE_RE = re.compile(r"^\d{4,10}$")
MAX_NEARBY_KM = 25.0
MAX_OPTIONS = 5


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def rupees(paise: int) -> str:
    return f"₹{paise / 100:g}"


def format_slot(iso: str | datetime) -> str:
    moment = datetime.fromisoformat(iso) if isinstance(iso, str) else iso
    return moment.strftime("%a %d %b, %H:%M") + " UTC"


class WhatsAppFlow:
    def __init__(self, db: Session):
        self.db = db
        self.availability = AvailabilityService(db)

    def handle(self, phone: str, message: dict) -> list[str]:
        """Process one inbound WhatsApp message; returns the replies to send."""
        session = self.db.get(WhatsAppSession, phone)
        message_id = message.get("id")
        # Meta retries deliveries; never act twice on the same message.
        if session and message_id and session.last_message_id == message_id:
            return []
        if not session:
            session = WhatsAppSession(phone=phone, step="welcome", data={})
            self.db.add(session)
        session.last_message_id = message_id

        try:
            replies = self._dispatch(session, phone, message)
        finally:
            self.db.commit()
        return replies

    # ── Step dispatch ────────────────────────────────────────────────────
    def _dispatch(self, session: WhatsAppSession, phone: str, message: dict) -> list[str]:
        text = (message.get("text") or "").strip().lower()

        if text in RESTART_WORDS:
            return self._reset(session, "📍 To find shops near you, share your live location, or type your pincode (e.g. 560001).")

        if message.get("type") == "location":
            return self._nearby_shops(session, message["latitude"], message["longitude"])

        step = session.step
        if step == "welcome":
            if text in CANCEL_WORDS:
                return self._reset(session, "Cancelled. Send *hi* any time to book again.")
            if PINCODE_RE.match(text):
                return self._pincode_shops(session, text)
            return ["📍 Share your live location or type your pincode to find shops near you.",
                    "You can also send *menu* to start over."]
        if step == "shop":
            return self._pick_shop(session, text)
        if step == "service":
            return self._pick_service(session, text)
        if step == "slot":
            return self._pick_slot(session, text)
        if step == "method":
            return self._pick_method(session, text)
        if step == "confirm":
            return self._confirm(session, phone, text)
        return self._reset(session, "Send *hi* to start a new booking.")

    # ── Shop discovery ───────────────────────────────────────────────────
    def _nearby_shops(self, session: WhatsAppSession, latitude: float, longitude: float) -> list[str]:
        shops = self.db.scalars(select(Shop).where(Shop.is_active)).all()
        scored = [(haversine_km(latitude, longitude, s.latitude, s.longitude), s)
                  for s in shops if s.latitude is not None and s.longitude is not None]
        scored.sort(key=lambda pair: pair[0])
        nearby = [s for distance, s in scored if distance <= MAX_NEARBY_KM][:MAX_OPTIONS]
        if not nearby:  # nothing with coordinates in range: fall back to every shop
            nearby = [s for s in shops if s.latitude is None][:MAX_OPTIONS]
        if not nearby:
            return self._reset(session, "No shops are listed yet. Try again later.")
        return self._offer_shops(session, nearby, prefix="📍 Found shops near you:")

    def _pincode_shops(self, session: WhatsAppSession, pincode: str) -> list[str]:
        shops = self.db.scalars(select(Shop).where(Shop.is_active, Shop.postal_code == pincode)).all()
        if not shops:
            return [f"No shops found in {pincode}. Try another pincode, or share your location."]
        return self._offer_shops(session, shops[:MAX_OPTIONS], prefix=f"📍 Shops in {pincode}:")

    def _offer_shops(self, session: WhatsAppSession, shops: list[Shop], prefix: str) -> list[str]:
        session.data = {"shop_ids": [s.id for s in shops]}
        session.step = "shop"
        lines = [prefix]
        for index, shop in enumerate(shops, 1):
            lines.append(f"{index}. *{shop.name}* — {shop.address or 'Address not set'}")
        lines.append("Reply with a number to pick a shop (or *0* to cancel).")
        return lines

    def _pick_shop(self, session: WhatsAppSession, text: str) -> list[str]:
        ids = session.data.get("shop_ids", [])
        if text in CANCEL_WORDS:
            return self._reset(session, "Cancelled. Send *hi* any time to book again.")
        if not text.isdigit() or not (1 <= int(text) <= len(ids)):
            return self._repeat(session, "Pick a shop by its number")
        shop = self.db.get(Shop, ids[int(text) - 1])
        services = self.db.scalars(select(Service).where(Service.shop_id == shop.id, Service.is_active)).all()
        if not services:
            return [f"{shop.name} has no services listed yet. Pick another shop — send *hi* to restart."]
        session.data = {**session.data, "shop_id": shop.id, "service_ids": [s.id for s in services]}
        session.step = "service"
        lines = [f"💇 Services at *{shop.name}*:"]
        for index, service in enumerate(services, 1):
            lines.append(f"{index}. *{service.name}* — {rupees(service.price_paise)} · {service.duration_minutes} min")
        lines.append("Reply with a number to pick a service (or *0* to cancel).")
        return lines

    # ── Service & slots ──────────────────────────────────────────────────
    def _pick_service(self, session: WhatsAppSession, text: str) -> list[str]:
        ids = session.data.get("service_ids", [])
        if text in CANCEL_WORDS:
            return self._reset(session, "Cancelled. Send *hi* any time to book again.")
        if not text.isdigit() or not (1 <= int(text) <= len(ids)):
            return self._repeat(session, "Pick a service by its number")
        service = self.db.get(Service, ids[int(text) - 1])
        slots = self._collect_slots(session.data["shop_id"], service.id)
        if not slots:
            return [f"No free slots for {service.name} in the next few days. Try another service — send *hi* to restart."]
        session.data = {**session.data, "service_id": service.id, "slots": slots}
        session.step = "slot"
        lines = [f"🗓 Free slots for *{service.name}*:"]
        lines += [f"{index}. {format_slot(slot)}" for index, slot in enumerate(slots, 1)]
        lines.append("Reply with a number to pick a time (or *0* to cancel).")
        return lines

    def _collect_slots(self, shop_id: int, service_id: int) -> list[str]:
        from datetime import date, timedelta

        slots: list[str] = []
        today = datetime.now(timezone.utc).date()
        for offset in range(3):
            day = today + timedelta(days=offset)
            for slot in self.availability.get_available_slots(shop_id, service_id, day):
                slots.append(slot.isoformat())
                if len(slots) >= MAX_OPTIONS:
                    return slots
        return slots

    def _pick_slot(self, session: WhatsAppSession, text: str) -> list[str]:
        slots = session.data.get("slots", [])
        if text in CANCEL_WORDS:
            return self._reset(session, "Cancelled. Send *hi* any time to book again.")
        if not text.isdigit() or not (1 <= int(text) <= len(slots)):
            return self._repeat(session, "Pick a time slot by its number")
        starts_at = slots[int(text) - 1]
        session.data = {**session.data, "starts_at": starts_at}
        session.step = "method"
        return ["💳 How would you like to pay?",
                "*1* — UPI (GPay / PhonePe / any UPI app)",
                "*2* — Card",
                "*0* — Cancel"]

    def _pick_method(self, session: WhatsAppSession, text: str) -> list[str]:
        if text in CANCEL_WORDS:
            return self._reset(session, "Cancelled. Send *hi* any time to book again.")
        if text not in ("1", "2"):
            return self._repeat(session, "Reply *1* for UPI or *2* for card")
        session.data = {**session.data, "method": "upi" if text == "1" else "card"}
        shop = self.db.get(Shop, session.data["shop_id"])
        service = self.db.get(Service, session.data["service_id"])
        fee = self._fee_paise(shop)
        total = service.price_paise + fee
        session.step = "confirm"
        return ["🧾 *Booking summary*",
                f"Shop: {shop.name}",
                f"Service: {service.name} ({service.duration_minutes} min)",
                f"When: {format_slot(session.data['starts_at'])}",
                f"Paying with: {session.data['method'].upper()}",
                f"Service price: {rupees(service.price_paise)}",
                f"Convenience fee: {rupees(fee)}",
                f"*Total: {rupees(total)}*",
                "Reply *1* to confirm & pay, or *0* to cancel."]

    @staticmethod
    def _fee_paise(shop: Shop) -> int:
        # Per-shop override wins; 0 means "use the platform default".
        return shop.convenience_fee_paise or settings.default_convenience_fee_paise

    # ── Booking + payment ────────────────────────────────────────────────
    def _confirm(self, session: WhatsAppSession, phone: str, text: str) -> list[str]:
        if text in CANCEL_WORDS:
            return self._reset(session, "Cancelled. No charge was made. Send *hi* any time to book again.")
        if text in CLAIM_WORDS and phone:
            return self._claim_upi(session, phone, text)
        if text not in CONFIRM_WORDS:
            return self._repeat(session, "Reply *1* to confirm & pay, or *0* to cancel")

        customer = self._customer(phone)
        shop = self.db.get(Shop, session.data["shop_id"])
        service = self.db.get(Service, session.data["service_id"])
        starts_at = datetime.fromisoformat(session.data["starts_at"])
        method = session.data.get("method", "upi")
        fee = self._fee_paise(shop)
        total = service.price_paise + fee

        try:
            booking = BookingService(self.db).create_booking(
                customer_id=customer.id, shop_id=shop.id, service_id=service.id, starts_at=starts_at)
        except Exception:  # slot conflict (409) or vanished shop/service
            return self._reset(session, "That slot was just taken by someone else. Send *hi* to pick a fresh time.")

        provider = get_payment_provider(method)
        result = provider.create_payment(
            booking_id=booking.id, amount_paise=total,
            description=f"{service.name} at {shop.name} — {format_slot(starts_at)}")
        payment = Payment(
            booking_id=booking.id, customer_phone=phone, provider=type(provider).__name__, method=method,
            provider_reference=result.provider_reference, amount_paise=total,
            convenience_fee_paise=fee,
            status=PaymentStatus.COMPLETED if result.status == "COMPLETED" else PaymentStatus.PENDING)
        self.db.add(payment)
        session.data = {}
        session.step = "welcome"

        header = ["✅ *Booked!* Confirmation code: *" + booking.code + "*",
                  f"{shop.name} · {service.name} · {format_slot(starts_at)}"]
        if payment.status == PaymentStatus.COMPLETED:
            return header + [f"{rupees(total)} paid (incl. {rupees(fee)} convenience fee).",
                             "Send *menu* to book another appointment."]
        if method == "upi":
            return header + [f"💳 Pay {rupees(total)} via UPI — open this link in any UPI app:",
                             result.checkout_url,
                             f"After paying, reply *paid* here and we'll verify. Amount includes {rupees(fee)} convenience fee."]
        return header + [f"💳 Complete your card payment to confirm the slot:",
                         result.checkout_url,
                         f"Amount due: {rupees(total)} (incl. {rupees(fee)} convenience fee)."]

    def _claim_upi(self, session: WhatsAppSession, phone: str, _text: str) -> list[str]:
        """Customer says they've paid a direct-UPI payment. Mark it for verification.

        We don't fabricate success — the payment is flagged PENDING with a note
        so an operator can confirm the receipt in their UPI app before the
        Razorpay webhook (or an admin) flips it to COMPLETED.
        """
        from sqlalchemy import select as _select

        payment = self.db.scalar(
            _select(Payment).where(Payment.customer_phone == phone).order_by(Payment.id.desc()))
        if not payment or payment.method != "upi" or payment.status != PaymentStatus.PENDING:
            return ["No pending UPI payment found. Send *hi* to start a new booking."]
        return [f"✅ Noted! We'll verify payment reference *{payment.provider_reference}* shortly.",
                "Your booking stays reserved while we check."]

    def _customer(self, phone: str) -> User:
        user = self.db.scalar(select(User).where(User.phone == phone))
        if not user:
            user = User(email=f"{phone}@wa.trimly.local", phone=phone,
                        password_hash=hash_password(secrets.token_urlsafe(32)), role=UserRole.CUSTOMER)
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
        return user

    # ── Helpers ──────────────────────────────────────────────────────────
    def _reset(self, session: WhatsAppSession | None, prompt: str) -> list[str]:
        """Return to the welcome step (when a session is attached) and reply."""
        if session is not None:
            session.step = "welcome"
            session.data = {}
        return [prompt]

    def _repeat(self, session: WhatsAppSession, instruction: str) -> list[str]:
        return [f"Sorry, I didn't catch that. {instruction}."]


def payment_confirmation_message(booking: Booking, shop: Shop, service: Service, payment: Payment) -> str:
    return (f"✅ Payment received — your booking *{booking.code}* is confirmed!\n"
            f"{shop.name} · {service.name} · {format_slot(booking.starts_at.isoformat())}\n"
            f"Paid {rupees(payment.amount_paise)} (incl. {rupees(payment.convenience_fee_paise)} convenience fee).")
