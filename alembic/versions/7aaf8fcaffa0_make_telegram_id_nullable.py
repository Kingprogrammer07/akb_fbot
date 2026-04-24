"""make telegram_id nullable

Revision ID: 7aaf8fcaffa0
Revises: validate_payment_provider
Create Date: 2026-01-15 21:48:41.002095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7aaf8fcaffa0'
down_revision: Union[str, None] = 'validate_payment_provider'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.alter_column(
        "clients",
        "telegram_id",
        existing_type=sa.BigInteger(),
        nullable=True
    )


def downgrade():
    op.alter_column(
        "clients",
        "telegram_id",
        existing_type=sa.BigInteger(),
        nullable=False
    )