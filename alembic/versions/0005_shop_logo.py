"""shop logo shown as the map avatar

Revision ID: 0005_shop_logo
Revises: 0004_reviews
"""
import sqlalchemy as sa
from sqlalchemy import inspect
from alembic import op

revision = "0005_shop_logo"
down_revision = "0004_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    shop_columns = {column["name"] for column in inspector.get_columns("shops")}
    if "logo_url" not in shop_columns:
        op.add_column("shops", sa.Column("logo_url", sa.String(500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    shop_columns = {column["name"] for column in inspector.get_columns("shops")}
    if "logo_url" in shop_columns:
        op.drop_column("shops", "logo_url")
