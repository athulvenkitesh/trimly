from urllib.parse import quote
from uuid import uuid4

from app.integrations.payments.provider import PaymentProvider, PaymentResult


class UpiIntentProvider(PaymentProvider):
    """Direct UPI intent payments.

    Builds the standard UPI deep-link (upi://pay?...) for the merchant VPA.
    No gateway, no per-transaction fees. Because a plain UPI intent gives the
    app no server-side callback, the customer confirms via the WhatsApp chat
    (or the web 'I've paid' button) and an admin verifies the receipt.
    """

    def __init__(self, vpa: str, payee_name: str = "Trimly"):
        self._vpa = vpa
        self._payee_name = payee_name

    def create_payment(self, *, booking_id: int, amount_paise: int, description: str = "") -> PaymentResult:
        reference = f"upi-{uuid4().hex[:12]}"
        rupees = amount_paise / 100
        note = description or f"Trimly booking #{booking_id}"
        intent = (
            f"upi://pay?pa={quote(self._vpa)}&pn={quote(self._payee_name)}"
            f"&am={rupees:.2f}&cu=INR&tn={quote(note)}&tr={reference}"
        )
        return PaymentResult(provider_reference=reference, status="PENDING", checkout_url=intent)
