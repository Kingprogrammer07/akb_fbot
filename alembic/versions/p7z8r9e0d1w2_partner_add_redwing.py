"""partner: add Red Wing (ZZ) cargo partner

Revision ID: p7z8r9e0d1w2
Revises: p6f7g8h9i0j1
Create Date: 2026-04-28 00:00:00.000000

Adds Red Wing cargo as a new non-DM partner with code ``ZZ`` and
prefix ``Z``.  Also inserts a paired ``partner_static_data`` row so
foto_hisobot can be configured later.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p7z8r9e0d1w2"
down_revision: Union[str, None] = "p6f7g8h9i0j1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "INSERT INTO partners (code, display_name, prefix, is_dm_partner, is_active) "
            "VALUES ('ZZ', 'Red Wing', 'Z', false, true)"
        )
    )

    bind.execute(
        sa.text(
            "INSERT INTO partner_static_data (partner_id) "
            "SELECT id FROM partners WHERE code = 'ZZ'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM partners WHERE code = 'ZZ'"))
