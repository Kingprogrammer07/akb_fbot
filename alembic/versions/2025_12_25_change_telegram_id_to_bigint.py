"""change telegram_id to bigint

Revision ID: 2025_12_25_bigint
Revises: 2025_12_22_extra_pass
Create Date: 2025-12-25 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2025_12_25_bigint'
down_revision: Union[str, None] = '2025_12_22_extra_pass'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change telegram_id columns from INTEGER to BIGINT."""
    # Change telegram_id in clients table to BIGINT
    op.alter_column('clients', 'telegram_id',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=False)

    # Change referrer_telegram_id in clients table to BIGINT
    op.alter_column('clients', 'referrer_telegram_id',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=True)


def downgrade() -> None:
    """Revert telegram_id columns back to INTEGER."""
    # Revert referrer_telegram_id back to INTEGER
    op.alter_column('clients', 'referrer_telegram_id',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=True)

    # Revert telegram_id back to INTEGER
    op.alter_column('clients', 'telegram_id',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=False)
