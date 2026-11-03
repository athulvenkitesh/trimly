import base64
import hmac
import hashlib
import httpx
from app.integrations.payments.provider import PaymentProvider, PaymentResult

class RazorpayPaymentProvider(PaymentProvider):
    """Creates Razorpay payment links; the webhook confirms them."""

    def __init__(self, api_key: str, base_url: str, webhook_secret: str = ""):
        # Razorpay keys are "key_id:key_secret" for basic auth on the REST API.
        self._key_id, _, self._key_secret = api_key.partition(":")
        self._base_url = base_url.rstrip("/")
        self._webhook_secret = webhook_secret

    def create_payment(self, *, booking_id: int, amount_paise: int, description: str = "") -> PaymentResult:
        response = httpx.post(
            "https://api.razorpay.com/v1/payment_links",
            auth=(self._key_id, self._key_secret),
            json={
                "amount": amount_paise,
                "currency": "INR",
                "description": description or f"Booking #{booking_id}",
                "callback_url": f"{self._base_url}/api/v1/payments/razorpay/callback",
                "callback_method": "get",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        return PaymentResult(provider_reference=payload["id"], status="PENDING", checkout_url=payload.get("short_url"))

    @staticmethod
    def verify_signature(body: bytes, signature: str, secret: str) -> bool:
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
