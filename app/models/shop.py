from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Platform convenience fee charged on top of the service price for WhatsApp payments.
    convenience_fee_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Shop logo/photo shown as the round avatar on the customer map and shop pages.
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    owner = relationship("User", back_populates="shops")
    services = relationship("Service", back_populates="shop", cascade="all, delete-orphan")
    business_hours = relationship("BusinessHours", back_populates="shop", cascade="all, delete-orphan")
    slot_settings = relationship("SlotSettings", back_populates="shop", uselist=False, cascade="all, delete-orphan")
