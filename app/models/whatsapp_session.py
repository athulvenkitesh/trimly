from datetime import datetime
from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class WhatsAppSession(Base):
    """Per-customer conversation state for the WhatsApp booking flow."""
    __tablename__ = "whatsapp_sessions"
    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    step: Mapped[str] = mapped_column(String(32), default="welcome")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    last_message_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
