"""Create static_data table

Revision ID: a7f4c8d3e2b9
Revises: f3d8e9a2b1c4
Create Date: 2026-01-02 17:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f4c8d3e2b9'
down_revision: Union[str, None] = 'f3d8e9a2b1c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create static_data table for admin settings and templates.

    This is a singleton configuration table - exactly one row with id=1.
    Includes all columns with proper server defaults.
    """
    # Check if table already exists (idempotent)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'static_data' in inspector.get_table_names():
        return

    op.create_table(
        'static_data',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("(NOW() AT TIME ZONE 'Asia/Tashkent')")),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("(NOW() AT TIME ZONE 'Asia/Tashkent')")),
        sa.Column('foto_hisobot', sa.Text(), nullable=False, server_default='',
                  comment='Photo report template text'),
        sa.Column('extra_charge', sa.Integer(), nullable=False, server_default='100',
                  comment='Extra charge amount'),
        sa.Column('price_per_kg', sa.Float(), nullable=False, server_default='9.5',
                  comment='Price per kilogram (e.g., 9.2, 10.4)'),
        sa.Column('notification', sa.Boolean(), nullable=False, server_default='false',
                  comment='Whether leftover cargo notifications are enabled'),
        sa.Column('notification_period', sa.Integer(), nullable=False, server_default='1',
                  comment='How often (in DAYS) notifications are sent (1-15 days)'),
        sa.PrimaryKeyConstraint('id')
    )

    # Insert singleton row with id=1 and default values
    op.execute(
        sa.text("""
            INSERT INTO static_data (id, created_at, updated_at, foto_hisobot, extra_charge, price_per_kg, notification, notification_period)
            VALUES (1, NOW() AT TIME ZONE 'Asia/Tashkent', NOW() AT TIME ZONE 'Asia/Tashkent', '', 100, 9.5, false, 1)
            ON CONFLICT (id) DO NOTHING
        """)
    )


def downgrade() -> None:
    """Drop static_data table."""
    op.drop_table('static_data')
