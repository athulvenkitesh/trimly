"""walk-in bookings without a customer account

Revision ID: 0006_walk_in_bookings
Revises: 0005_shop_logo
"""
import sqlalchemy as sa
from sqlalchemy import inspect
from alembic import op

revision = "0006_walk_in_bookings"
down_revision = "0005_shop_logo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    booking_columns = {column["name"]: column for column in inspector.get_columns("bookings")}
    if "walk_in_name" not in booking_columns:
        op.add_column("bookings", sa.Column("walk_in_name", sa.String(120), nullable=True))
    customer_id = booking_columns.get("customer_id")
    if customer_id is not None and not customer_id["nullable"]:
        op.alter_column("bookings", "customer_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    booking_columns = {column["name"]: column for column in inspector.get_columns("bookings")}
    if "walk_in_name" in booking_columns:
        op.drop_column("bookings", "walk_in_name")
    # Walk-in rows have no customer, so they cannot survive a non-null constraint.
    op.execute("DELETE FROM bookings WHERE customer_id IS NULL")
    op.alter_column("bookings", "customer_id", existing_type=sa.Integer(), nullable=False)
