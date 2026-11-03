"""customer reviews: rating + comment per shop

Revision ID: 0004_reviews
Revises: 0003_whatsapp_payments
"""
import sqlalchemy as sa
from sqlalchemy import inspect
from alembic import op
from app.core.database import Base
import app.models  # noqa: F401  (register tables on Base.metadata)

revision = "0004_reviews"
down_revision = "0003_whatsapp_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("reviews"):
        Base.metadata.tables["reviews"].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("reviews"):
        op.drop_table("reviews")
