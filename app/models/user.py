import enum
from datetime import datetime
from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

class UserRole(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    SHOP_OWNER = "SHOP_OWNER"
    ADMIN = "ADMIN"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.CUSTOMER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    shops = relationship("Shop", back_populates="owner")
