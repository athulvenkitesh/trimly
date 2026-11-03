from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price_paise: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    shop = relationship("Shop", back_populates="services")
