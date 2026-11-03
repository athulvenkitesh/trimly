"""whatsapp booking: user phone, shop convenience fee, payments, sessions

Revision ID: 0003_whatsapp_payments
Revises: 0002_shop_location
"""
import sqlalchemy as sa
from sqlalchemy import inspect
from alembic import op
from app.core.database import Base
import app.models  # noqa: F401  (register tables on Base.metadata)

revision = "0003_whatsapp_payments"
down_revision = "0002_shop_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "phone" not in user_columns:
        op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
        # Partial unique index: many portal-only users have no phone.
        bind.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone ON users (phone)")

    shop_columns = {column["name"] for column in inspector.get_columns("shops")}
    if "convenience_fee_paise" not in shop_columns:
        op.add_column("shops", sa.Column("convenience_fee_paise", sa.Integer(), nullable=False, server_default="0"))

    for table in ("payments", "whatsapp_sessions"):
        if not inspector.has_table(table):
            Base.metadata.tables[table].create(bind, checkfirst=True)

    payment_columns = {column["name"] for column in inspector.get_columns("payments")}
    if "method" not in payment_columns:
        op.add_column("payments", sa.Column("method", sa.String(16), nullable=False, server_default="upi"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table in ("payments", "whatsapp_sessions"):
        if inspector.has_table(table):
            Base.metadata.tables[table].drop(bind)
    payment_columns = {column["name"] for column in inspector.get_columns("payments")}
    if "method" in payment_columns:
        op.drop_column("payments", "method")
    shop_columns = {column["name"] for column in inspector.get_columns("shops")}
    if "convenience_fee_paise" in shop_columns:
        op.drop_column("shops", "convenience_fee_paise")
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "phone" in user_columns:
        bind.exec_driver_sql("DROP INDEX IF EXISTS ix_users_phone")
        op.drop_column("users", "phone")
