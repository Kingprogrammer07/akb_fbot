"""partner masking phase 4a: GGX consolidation + multi-char prefixes

Revision ID: p2g3g4x5y6z7
Revises: p1a2r3t4n5e6
Create Date: 2026-04-26 12:00:00.000000

Changes:

1. Widen ``partners.prefix`` from VARCHAR(1) → VARCHAR(8) and replace the
   ``ck_partner_prefix_len_1`` CHECK with ``char_length(prefix) BETWEEN 1 AND 8``.
2. Insert the ``GGX`` partner row representing the AKB Xorazm filiali —
   previously routed via the ``AKB_XORAZM_FILIALI_GROUP_ID`` env var.
   ``group_chat_id`` is initialised from the env var when present so the
   migration is zero-touch for the existing deployment.
3. Insert paired ``partner_static_data`` row.
"""
from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p2g3g4x5y6z7"
down_revision: Union[str, None] = "p1a2r3t4n5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _env_xorazm_group_id() -> int | None:
    raw = os.getenv("AKB_XORAZM_FILIALI_GROUP_ID")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def upgrade() -> None:
    # 1. Drop the old length-1 constraint and widen the column.
    op.drop_constraint("ck_partner_prefix_len_1", "partners", type_="check")
    op.alter_column(
        "partners",
        "prefix",
        existing_type=sa.String(length=1),
        type_=sa.String(length=8),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_partner_prefix_len_range",
        "partners",
        "char_length(prefix) BETWEEN 1 AND 8",
    )

    # 2. Insert the GGX partner row.  Skip if it already exists so the
    #    migration is idempotent on partial reruns.
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT 1 FROM partners WHERE code = 'GGX'")
    ).scalar()
    if not existing:
        bind.execute(
            sa.text(
                "INSERT INTO partners "
                "(code, display_name, prefix, group_chat_id, is_dm_partner, is_active) "
                "VALUES (:code, :display_name, :prefix, :group_chat_id, false, true)"
            ),
            {
                "code": "GGX",
                "display_name": "AKB Xorazm filiali",
                "prefix": "GGX",
                "group_chat_id": _env_xorazm_group_id(),
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO partner_static_data (partner_id, foto_hisobot) "
                "SELECT id, '' FROM partners WHERE code = 'GGX'"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM partners WHERE code = 'GGX'"))

    op.drop_constraint(
        "ck_partner_prefix_len_range", "partners", type_="check"
    )
    op.alter_column(
        "partners",
        "prefix",
        existing_type=sa.String(length=8),
        type_=sa.String(length=1),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_partner_prefix_len_1",
        "partners",
        "char_length(prefix) = 1",
    )
