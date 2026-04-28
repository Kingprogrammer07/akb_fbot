"""Create clients table

Revision ID: 2025_12_21_001
Revises:
Create Date: 2025-12-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2025_12_21_001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    table_exists = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'clients')")
    ).scalar()

    if not table_exists:
        op.create_table(
            'clients',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('telegram_id', sa.BigInteger(), nullable=False),
            sa.Column('full_name', sa.String(length=256), nullable=False),
            sa.Column('phone', sa.String(length=20), nullable=True),
            sa.Column('language_code', sa.String(length=5), nullable=False, server_default='uz'),
            sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('passport_series', sa.String(length=10), nullable=True),
            sa.Column('pinfl', sa.String(length=14), nullable=True),
            sa.Column('date_of_birth', sa.Date(), nullable=True),
            sa.Column('region', sa.String(length=128), nullable=True),
            sa.Column('address', sa.String(length=512), nullable=True),
            sa.Column('passport_images', sa.Text(), nullable=True),
            sa.Column('client_code', sa.String(length=10), nullable=True),
            sa.Column('referrer_telegram_id', sa.BigInteger(), nullable=True),
            sa.Column('referrer_client_code', sa.String(length=10), nullable=True),
            sa.Column('is_logged_in', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('telegram_id'),
            sa.UniqueConstraint('client_code')
        )

    index_exists = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_clients_telegram_id')")
    ).scalar()
    if not index_exists:
        op.create_index('ix_clients_telegram_id', 'clients', ['telegram_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_clients_telegram_id', table_name='clients')
    op.drop_table('clients')
