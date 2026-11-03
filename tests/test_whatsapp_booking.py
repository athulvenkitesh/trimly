import hashlib
import hmac
import json
from datetime import date, time, timedelta

owner_payload = {"email": "waowner@example.com", "password": "password123", "role": "SHOP_OWNER"}


def register_owner(client):
    tokens = client.post("/api/v1/auth/register", json=owner_payload).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def seed_shop(client, headers, fee_paise=2500):
    shop = client.post("/api/v1/shops", headers=headers, json={
        "name": "Cut Here", "address": "12 Market Street",
        "latitude": 12.9716, "longitude": 77.5946, "postal_code": "560001"}).json()
    client.put(f"/api/v1/barber/shops/{shop['id']}/convenience-fee", headers=headers,
               json={"convenience_fee_paise": fee_paise})
    service = client.post(f"/api/v1/shops/{shop['id']}/services", headers=headers,
                          json={"name": "Haircut", "duration_minutes": 30, "price_paise": 25000}).json()
    # Open every weekday so the flow always has slots to offer.
    for weekday in range(7):
        client.put(f"/api/v1/barber/shops/{shop['id']}/business-hours", headers=headers, json={
            "weekday": weekday, "opens_at": "09:00", "closes_at": "18:00", "is_closed": False})
    return shop, service


def send_webhook(client, phone, message, message_id="wamid-1"):
    if message.get("type") == "location":
        body = {"from": phone, "id": message_id, "type": "location",
                "location": {"latitude": message["latitude"], "longitude": message["longitude"]}}
    else:
        body = {"from": phone, "id": message_id, "type": "text", "text": {"body": message["text"]}}
    payload = {"entry": [{"changes": [{"value": {"messages": [body]}}]}]}
    return client.post("/api/v1/whatsapp/webhook", json=payload)


def test_webhook_verification(client):
    ok = client.get("/api/v1/whatsapp/webhook",
                    params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "12345"})
    # Dev config has an empty verify token; matching empty tokens still pass the handshake.
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get("/api/v1/whatsapp/webhook",
                     params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "12345"})
    assert bad.status_code == 403


def test_full_chat_booking_flow_with_convenience_fee(client):
    headers = register_owner(client)
    shop, service = seed_shop(client, headers, fee_paise=2500)
    phone = "911234567890"

    assert send_webhook(client, phone, {"text": "hi"}).status_code == 200
    assert send_webhook(client, phone, {"type": "location", "latitude": 12.972, "longitude": 77.595},
                        message_id="wamid-2").status_code == 200
    assert send_webhook(client, phone, {"text": "1"}, message_id="wamid-3").status_code == 200
    assert send_webhook(client, phone, {"text": "1"}, message_id="wamid-4").status_code == 200
    assert send_webhook(client, phone, {"text": "1"}, message_id="wamid-5").status_code == 200
    # Payment-method step: choose card this time.
    assert send_webhook(client, phone, {"text": "2"}, message_id="wamid-5b").status_code == 200
    # Booking summary shown; confirm & pay.
    assert send_webhook(client, phone, {"text": "1"}, message_id="wamid-6").status_code == 200

    # Replaying the same delivery must not create a second booking.
    assert send_webhook(client, phone, {"text": "1"}, message_id="wamid-6").status_code == 200

    # The WhatsApp customer account exists with the phone attached.
    from app.core.database import SessionLocal
    from app.models import Booking, Payment, PaymentStatus, User, WhatsAppSession
    db = SessionLocal()
    try:
        customer = db.query(User).filter(User.phone == phone).one()
        bookings = db.query(Booking).filter(Booking.customer_id == customer.id).all()
        assert len(bookings) == 1
        payment = db.query(Payment).filter(Payment.booking_id == bookings[0].id).one()
        # Service ₹250 + convenience fee ₹25 = ₹270, paid by card.
        assert payment.amount_paise == 25000 + 2500
        assert payment.convenience_fee_paise == 2500
        assert payment.method == "card"
        assert payment.status == PaymentStatus.COMPLETED  # mock provider completes instantly
        session = db.query(WhatsAppSession).filter(WhatsAppSession.phone == phone).one()
        assert session.step == "welcome"  # reset for the next booking
    finally:
        db.close()


def test_pincode_discovers_shops_and_confirms_payment(client):
    headers = register_owner(client)
    shop, service = seed_shop(client, headers, fee_paise=0)
    phone = "919988776655"

    send_webhook(client, phone, {"text": "book"}, message_id="m1")
    send_webhook(client, phone, {"text": "560001"}, message_id="m2")
    send_webhook(client, phone, {"text": "1"}, message_id="m3")
    send_webhook(client, phone, {"text": "1"}, message_id="m4")
    send_webhook(client, phone, {"text": "1"}, message_id="m5")
    send_webhook(client, phone, {"text": "1"}, message_id="m5b")  # method: UPI
    send_webhook(client, phone, {"text": "yes"}, message_id="m6")

    from app.core.database import SessionLocal
    from app.models import Booking, Payment, User
    db = SessionLocal()
    try:
        customer = db.query(User).filter(User.phone == phone).one()
        booking = db.query(Booking).filter(Booking.customer_id == customer.id).one()
        payment = db.query(Payment).filter(Payment.booking_id == booking.id).one()
        # Fee 0 means "use the platform default" (2000 paise in dev config); UPI method.
        assert payment.convenience_fee_paise == 2000
        assert payment.amount_paise == 25000 + 2000
        assert payment.method == "upi"
    finally:
        db.close()


def test_convenience_fee_endpoint(client):
    headers = register_owner(client)
    shop, _ = seed_shop(client, headers, fee_paise=1000)

    # Owner can read back the fee via the shop list and change it.
    shops = client.get("/api/v1/barber/shops", headers=headers).json()
    mine = next(s for s in shops if s["id"] == shop["id"])
    assert mine["convenience_fee_paise"] == 1000

    changed = client.put(f"/api/v1/barber/shops/{shop['id']}/convenience-fee",
                         headers=headers, json={"convenience_fee_paise": 5000})
    assert changed.status_code == 200 and changed.json()["convenience_fee_paise"] == 5000

    # Validation and ownership.
    assert client.put(f"/api/v1/barber/shops/{shop['id']}/convenience-fee",
                      headers=headers, json={"convenience_fee_paise": -5}).status_code == 422
    other = client.post("/api/v1/auth/register", json={
        "email": "other2@example.com", "password": "password123", "role": "SHOP_OWNER"}).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.put(f"/api/v1/barber/shops/{shop['id']}/convenience-fee",
                      headers=other_headers, json={"convenience_fee_paise": 5000}).status_code == 403


def test_payment_webhook_completes_pending_payment(client, monkeypatch):
    # Force the flow down the PENDING path with a stub provider.
    from app.integrations.payments.provider import PaymentResult
    from app.services import whatsapp_flow

    class PendingProvider:
        def create_payment(self, *, booking_id, amount_paise, description=""):
            return PaymentResult(provider_reference="paylink_abc123", status="PENDING",
                                 checkout_url="https://rzp.io/paylink_abc123")

    monkeypatch.setattr(whatsapp_flow, "get_payment_provider", lambda *args, **kwargs: PendingProvider())

    headers = register_owner(client)
    shop, service = seed_shop(client, headers, fee_paise=1500)
    phone = "911122334455"
    for index, text in enumerate(["hi", "560001", "1", "1", "1", "1", "1"], start=1):
        send_webhook(client, phone, {"text": text}, message_id=f"p{index}")

    from app.core.database import SessionLocal
    from app.models import Booking, Payment, PaymentStatus
    db = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.customer_phone == phone).one()
        assert payment.status == PaymentStatus.PENDING
        booking = db.get(Booking, payment.booking_id)
    finally:
        db.close()

    # Razorpay-style payment_link.completed event confirms the payment.
    secret = "whsec_test"
    from app.core.config import settings
    monkeypatch.setattr(settings, "payment_webhook_secret", secret)
    event = {"event": "payment_link.completed",
             "payload": {"payment": {"entity": {"payment_link_id": "paylink_abc123"}}}}
    raw = json.dumps(event).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    response = client.post("/api/v1/payments/razorpay/webhook", content=raw,
                           headers={"Content-Type": "application/json", "X-Razorpay-Signature": signature})
    assert response.status_code == 200

    db = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.customer_phone == phone).one()
        assert payment.status == PaymentStatus.COMPLETED
    finally:
        db.close()

    # Bad signature is rejected.
    bad = client.post("/api/v1/payments/razorpay/webhook", content=raw,
                      headers={"Content-Type": "application/json", "X-Razorpay-Signature": "deadbeef"})
    assert bad.status_code == 403


def test_web_booking_with_upi_and_card_methods(client, monkeypatch):
    """The web app lets a customer pay with UPI or card."""
    owner = client.post("/api/v1/auth/register", json={"email": "methods@example.com", "password": "password123", "role": "SHOP_OWNER"}).json()
    oheaders = {"Authorization": f"Bearer {owner['access_token']}"}
    shop = client.post("/api/v1/shops", headers=oheaders, json={"name": "Methods Cuts", "latitude": 12.97, "longitude": 77.6}).json()
    client.put(f"/api/v1/barber/shops/{shop['id']}/convenience-fee", headers=oheaders, json={"convenience_fee_paise": 1000})
    service = client.post(f"/api/v1/shops/{shop['id']}/services", headers=oheaders, json={"name": "Fade", "duration_minutes": 30, "price_paise": 20000}).json()
    for weekday in range(7):
        client.put(f"/api/v1/barber/shops/{shop['id']}/business-hours", headers=oheaders, json={"weekday": weekday, "opens_at": "09:00", "closes_at": "18:00", "is_closed": False})

    from app.core.config import settings
    # Give the shop a UPI VPA so UPI goes down the intent path.
    monkeypatch.setattr(settings, "upi_vpa", "shop@upi")

    cust = client.post("/api/v1/auth/register", json={"email": "methodcust@example.com", "password": "password123", "role": "CUSTOMER"}).json()
    cheaders = {"Authorization": f"Bearer {cust['access_token']}"}
    day = (date.today() + timedelta(days=2)).isoformat()
    slot = client.get(f"/api/v1/shops/{shop['id']}/availability?service_id={service['id']}&date={day}").json()["slots"][0]
    booking = client.post("/api/v1/bookings", headers=cheaders, json={"shop_id": shop["id"], "service_id": service["id"], "starts_at": slot}).json()

    # UPI: pending with an upi:// intent link.
    upi = client.post(f"/api/v1/customer/bookings/{booking['id']}/pay", headers=cheaders, params={"method": "upi"}).json()
    assert upi["payment_status"] == "PENDING"
    assert upi["method"] == "upi"
    assert upi["checkout_url"].startswith("upi://pay?")
    assert upi["amount_paise"] == 20000 + 1000

    # UPI rejects double-pay.
    again = client.post(f"/api/v1/customer/bookings/{booking['id']}/pay", headers=cheaders, params={"method": "upi"})
    assert again.status_code == 409

    # Card: mock provider completes instantly when Razorpay is not configured.
    booking2 = client.post("/api/v1/bookings", headers=cheaders, json={"shop_id": shop["id"], "service_id": service["id"],
                                                                         "starts_at": client.get(f"/api/v1/shops/{shop['id']}/availability?service_id={service['id']}&date={day}").json()["slots"][1]}).json()
    card = client.post(f"/api/v1/customer/bookings/{booking2['id']}/pay", headers=cheaders, params={"method": "card"}).json()
    assert card["method"] == "card"
    assert card["payment_status"] == "COMPLETED"

    # Invalid method rejected.
    booking3 = client.post("/api/v1/bookings", headers=cheaders, json={"shop_id": shop["id"], "service_id": service["id"],
                                                                         "starts_at": client.get(f"/api/v1/shops/{shop['id']}/availability?service_id={service['id']}&date={day}").json()["slots"][2]}).json()
    bad = client.post(f"/api/v1/customer/bookings/{booking3['id']}/pay", headers=cheaders, params={"method": "netbanking"})
    assert bad.status_code == 422
