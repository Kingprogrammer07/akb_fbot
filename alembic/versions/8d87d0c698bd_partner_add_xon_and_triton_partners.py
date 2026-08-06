"""partner: add xon and triton partners

Revision ID: 8d87d0c698bd
Revises: p9r0s1t2u3v4
Create Date: 2026-08-06 18:49:16.415785

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d87d0c698bd'
down_revision: Union[str, None] = 'p9r0s1t2u3v4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    
    # 1. Insert Xon kargo
    bind.execute(
        sa.text(
            "INSERT INTO partners (code, display_name, prefix, group_chat_id, is_dm_partner, is_active) "
            "VALUES ('H', 'Xon kargo', 'H', -1004413972118, false, true) "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO partner_static_data (partner_id) "
            "SELECT id FROM partners WHERE code = 'H' "
            "ON CONFLICT (partner_id) DO NOTHING"
        )
    )

    # 2. Insert Triton
    bind.execute(
        sa.text(
            "INSERT INTO partners (code, display_name, prefix, group_chat_id, is_dm_partner, is_active) "
            "VALUES ('SYT', 'Triton', 'SYT', -1004380311675, false, true) "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO partner_static_data (partner_id) "
            "SELECT id FROM partners WHERE code = 'SYT' "
            "ON CONFLICT (partner_id) DO NOTHING"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM partners WHERE code IN ('H', 'SYT')"))
