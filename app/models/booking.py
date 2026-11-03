import enum
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class BookingStatus(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"

class Booking(Base):
    __tablename__ = "bookings"
    # A PostgreSQL partial unique index is the final concurrency guard.  Application
    # locking improves the error path; this constraint makes double-booking impossible.
    __table_args__ = (Index("uq_active_booking_shop_start", "shop_id", "starts_at", unique=True,
                            postgresql_where=text("status = 'CONFIRMED'"),
                            sqlite_where=text("status = 'CONFIRMED'")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    # Null for walk-ins the owner seats at the counter: they still occupy the slot.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    walk_in_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.CONFIRMED)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
