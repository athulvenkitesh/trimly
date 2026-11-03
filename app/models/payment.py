import enum
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    customer_phone: Mapped[str] = mapped_column(String(20), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    # "upi" or "card" — how the customer chose to pay.
    method: Mapped[str] = mapped_column(String(16), default="upi")
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    convenience_fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
