"""shop location columns

Revision ID: 0002_shop_location
Revises: 0001_initial
"""
from sqlalchemy import inspect
from alembic import op
from app.core.database import Base
import app.models  # noqa: F401

revision = "0002_shop_location"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

COLUMNS = {
    "latitude": "ALTER TABLE shops ADD COLUMN latitude FLOAT",
    "longitude": "ALTER TABLE shops ADD COLUMN longitude FLOAT",
    "place_id": "ALTER TABLE shops ADD COLUMN place_id VARCHAR(255)",
    "postal_code": "ALTER TABLE shops ADD COLUMN postal_code VARCHAR(20)",
}

def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("shops")}
    for name, statement in COLUMNS.items():
        if name not in existing:
            bind.exec_driver_sql(statement)

def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("shops")}
    for name in COLUMNS:
        if name in existing:
            bind.exec_driver_sql(f"ALTER TABLE shops DROP COLUMN {name}")
