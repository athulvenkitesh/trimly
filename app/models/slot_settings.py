from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class SlotSettings(Base):
    __tablename__ = "slot_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), unique=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    shop = relationship("Shop", back_populates="slot_settings")
