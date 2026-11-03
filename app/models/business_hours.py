from datetime import time
from sqlalchemy import Boolean, ForeignKey, Integer, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class BusinessHours(Base):
    __tablename__ = "business_hours"
    __table_args__ = (UniqueConstraint("shop_id", "weekday", name="uq_business_hours_shop_weekday"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)  # Monday=0
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    shop = relationship("Shop", back_populates="business_hours")
