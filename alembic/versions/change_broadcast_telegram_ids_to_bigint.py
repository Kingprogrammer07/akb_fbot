"""Change broadcast telegram_id and chat_id columns to BIGINT

Revision ID: change_broadcast_ids_bigint
Revises: 7aaf8fcaffa0
Create Date: 2026-01-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'change_broadcast_ids_bigint'
down_revision: Union[str, None] = '7aaf8fcaffa0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Change Integer columns to BigInteger for Telegram IDs.

    Telegram user/chat IDs can exceed int32 range (2^31-1 = 2,147,483,647).
    This migration safely converts existing data.
    """
    # Change created_by_telegram_id from INTEGER to BIGINT
    op.alter_column(
        'broadcast_messages',
        'created_by_telegram_id',
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        comment='Telegram ID of admin who created this broadcast'
    )

    # Change forward_from_chat_id from INTEGER to BIGINT
    op.alter_column(
        'broadcast_messages',
        'forward_from_chat_id',
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
        comment='Chat ID to forward from'
    )


def downgrade() -> None:
    """
    Revert BigInteger columns back to Integer.

    WARNING: This may fail if any values exceed int32 range.
    """
    # Revert forward_from_chat_id to INTEGER
    op.alter_column(
        'broadcast_messages',
        'forward_from_chat_id',
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
        comment='Chat ID to forward from'
    )

    # Revert created_by_telegram_id to INTEGER
    op.alter_column(
        'broadcast_messages',
        'created_by_telegram_id',
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        comment='Telegram ID of admin who created this broadcast'
    )
