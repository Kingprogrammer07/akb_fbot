"""Create delivery_requests table

Revision ID: d5e6f7a8b9c0
Revises: 439e07b6800b
Create Date: 2026-01-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = '439e07b6800b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create delivery_requests table for delivery request management."""
    op.create_table(
        'delivery_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('client_code', sa.String(10), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('delivery_type', sa.String(20), nullable=False, comment='uzpost, yandex, akb, bts'),
        sa.Column('flight_names', sa.Text(), nullable=False, comment='JSON array of flight names'),
        sa.Column('full_name', sa.String(256), nullable=False),
        sa.Column('phone', sa.String(20), nullable=False),
        sa.Column('region', sa.String(128), nullable=False),
        sa.Column('address', sa.String(512), nullable=False),
        sa.Column('prepayment_receipt_file_id', sa.Text(), nullable=True, comment='File ID of prepayment receipt for UZPOST'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', comment='pending, approved, rejected'),
        sa.Column('admin_comment', sa.Text(), nullable=True),
        sa.Column('processed_by_admin_id', sa.BigInteger(), nullable=True),
        sa.Column('processed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for faster lookups
    op.create_index('idx_delivery_requests_client_id', 'delivery_requests', ['client_id'])
    op.create_index('idx_delivery_requests_telegram_id', 'delivery_requests', ['telegram_id'])
    op.create_index('idx_delivery_requests_status', 'delivery_requests', ['status'])


def downgrade() -> None:
    """Drop delivery_requests table."""
    op.drop_index('idx_delivery_requests_status', 'delivery_requests')
    op.drop_index('idx_delivery_requests_telegram_id', 'delivery_requests')
    op.drop_index('idx_delivery_requests_client_id', 'delivery_requests')
    op.drop_table('delivery_requests')
