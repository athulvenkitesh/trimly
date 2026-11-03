from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Review(Base):
    """Customer review left after a booking at a shop.

    Tied to a booking so only genuine customers can review (enforced in the
    route), and unique per booking so a visit can't be rated twice.
    """

    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("booking_id", name="uq_review_per_booking"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    rating: Mapped[int] = mapped_column(Integer)  # 1..5, bounded in the schema
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
