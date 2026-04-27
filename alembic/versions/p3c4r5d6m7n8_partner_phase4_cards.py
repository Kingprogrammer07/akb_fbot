"""partner masking phase 4c: migrate payment_cards → partner_payment_methods

Revision ID: p3c4r5d6m7n8
Revises: p2g3g4x5y6z7
Create Date: 2026-04-26 13:00:00.000000

The legacy ``payment_cards`` table is a single global pool that was
shared by every cargo report sent through the bot.  Since the bot is
AKB-only, every existing row belongs to the AKB partner.  This migration
copies them into ``partner_payment_methods`` rows for that partner so the
new per-partner rendering path is the single source of truth.

The original ``payment_cards`` table is kept intact so the legacy
``PaymentCardDAO`` keeps working for any caller that has not migrated
yet.  It is dropped in a follow-up cleanup migration.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p3c4r5d6m7n8"
down_revision: Union[str, None] = "p2g3g4x5y6z7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    akb_partner_id = bind.execute(
        sa.text("SELECT id FROM partners WHERE code = 'AKB'")
    ).scalar()
    if akb_partner_id is None:
        # Partner table not yet seeded → nothing to do.
        return

    # Copy each payment_cards row into partner_payment_methods as a 'card'
    # method linked to AKB.  Skips rows whose card_number already exists for
    # AKB to keep the migration idempotent on partial reruns.
    bind.execute(
        sa.text(
            """
            INSERT INTO partner_payment_methods
                (partner_id, method_type, card_number, card_holder, is_active, weight,
                 created_at, updated_at)
            SELECT
                :partner_id,
                'card',
                pc.card_number,
                pc.full_name,
                pc.is_active,
                1,
                COALESCE(pc.created_at, now()),
                COALESCE(pc.updated_at, now())
            FROM payment_cards pc
            WHERE NOT EXISTS (
                SELECT 1 FROM partner_payment_methods ppm
                 WHERE ppm.partner_id = :partner_id
                   AND ppm.method_type = 'card'
                   AND ppm.card_number = pc.card_number
            )
            """
        ),
        {"partner_id": akb_partner_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    akb_partner_id = bind.execute(
        sa.text("SELECT id FROM partners WHERE code = 'AKB'")
    ).scalar()
    if akb_partner_id is None:
        return

    # Remove only those AKB cards whose card_number still appears in
    # payment_cards — leaves any cards added directly via the new admin
    # endpoints intact.
    bind.execute(
        sa.text(
            """
            DELETE FROM partner_payment_methods ppm
             WHERE ppm.partner_id = :partner_id
               AND ppm.method_type = 'card'
               AND ppm.card_number IN (SELECT card_number FROM payment_cards)
            """
        ),
        {"partner_id": akb_partner_id},
    )
