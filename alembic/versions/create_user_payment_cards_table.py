"""Create user_payment_cards table

Revision ID: create_user_payment_cards
Revises: e07d6d2fcd61
Create Date: 2026-01-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'create_user_payment_cards'
down_revision: Union[str, None] = 'e07d6d2fcd61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if a table already exists."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not table_exists('user_payment_cards'):
        op.create_table(
            'user_payment_cards',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('telegram_id', sa.BigInteger(), nullable=False),
            sa.Column('card_number', sa.String(19), nullable=False),
            sa.Column('holder_name', sa.String(255), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                       server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False,
                       server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_user_payment_cards_telegram_id',
            'user_payment_cards',
            ['telegram_id']
        )


def downgrade() -> None:
    if table_exists('user_payment_cards'):
        op.drop_index('ix_user_payment_cards_telegram_id', table_name='user_payment_cards')
        op.drop_table('user_payment_cards')
