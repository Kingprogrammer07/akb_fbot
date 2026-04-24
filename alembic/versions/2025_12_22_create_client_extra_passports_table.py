"""create_client_extra_passports_table

Revision ID: 2025_12_22_extra_pass
Revises: 2025_12_21_001
Create Date: 2025-12-22 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2025_12_22_extra_pass'
down_revision: Union[str, None] = '2025_12_21_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create client_extra_passports table."""
    op.create_table(
        'client_extra_passports',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('client_code', sa.String(length=10), nullable=True),
        sa.Column('passport_series', sa.String(length=10), nullable=False),
        sa.Column('pinfl', sa.String(length=14), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=False),
        sa.Column('passport_images', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_client_extra_passports_telegram_id', 'client_extra_passports', ['telegram_id'])
    op.create_index('ix_client_extra_passports_client_code', 'client_extra_passports', ['client_code'])


def downgrade() -> None:
    """Drop client_extra_passports table."""
    op.drop_index('ix_client_extra_passports_client_code', table_name='client_extra_passports')
    op.drop_index('ix_client_extra_passports_telegram_id', table_name='client_extra_passports')
    op.drop_table('client_extra_passports')
