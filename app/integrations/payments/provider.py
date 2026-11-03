from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class PaymentResult:
    provider_reference: str
    status: str
    checkout_url: str | None = None

class PaymentProvider(ABC):
    """Provider boundary; implementations must never mutate bookings directly."""
    @abstractmethod
    def create_payment(self, *, booking_id: int, amount_paise: int, description: str = "") -> PaymentResult: ...

class PaymentService:
    def __init__(self, provider: PaymentProvider):
        self.provider = provider

    def request_payment(self, booking_id: int, amount_paise: int, description: str = "") -> PaymentResult:
        return self.provider.create_payment(booking_id=booking_id, amount_paise=amount_paise, description=description)


def get_payment_provider(method: str = "upi"):
    """Pick the provider for a payment method.

    card -> Razorpay when configured, mock otherwise.
    upi  -> direct UPI intent when a VPA is set; Razorpay (aggregator UPI)
            when Razorpay is configured without a direct VPA; mock otherwise.
    """
    from app.core.config import settings

    razorpay_ready = settings.payment_provider.lower() == "razorpay" and settings.payment_api_key
    method = (method or "upi").lower()

    if method == "card":
        if razorpay_ready:
            from app.integrations.payments.razorpay import RazorpayPaymentProvider

            return RazorpayPaymentProvider(settings.payment_api_key, settings.public_base_url, settings.payment_webhook_secret)
        from app.integrations.payments.mock import MockPaymentProvider

        return MockPaymentProvider()

    # UPI: prefer the direct keyless intent when a VPA is configured.
    if settings.upi_vpa:
        from app.integrations.payments.upi import UpiIntentProvider

        return UpiIntentProvider(settings.upi_vpa, settings.upi_payee_name)
    if razorpay_ready:
        from app.integrations.payments.razorpay import RazorpayPaymentProvider

        return RazorpayPaymentProvider(settings.payment_api_key, settings.public_base_url, settings.payment_webhook_secret)
    from app.integrations.payments.mock import MockPaymentProvider

    return MockPaymentProvider()
