from uuid import uuid4
from app.integrations.payments.provider import PaymentProvider, PaymentResult

class MockPaymentProvider(PaymentProvider):
    """Dev/test provider: completes instantly so the booking flow is exercisable offline."""

    def create_payment(self, *, booking_id: int, amount_paise: int, description: str = "") -> PaymentResult:
        return PaymentResult(provider_reference=f"mockpay-{uuid4().hex[:16]}", status="COMPLETED")
