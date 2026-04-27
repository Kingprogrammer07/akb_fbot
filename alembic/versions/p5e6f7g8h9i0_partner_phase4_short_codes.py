"""partner masking phase 4e: shorten non-AKB partner codes + drop GGX

Revision ID: p5e6f7g8h9i0
Revises: p4a5k6b7p8q9
Create Date: 2026-04-27 00:00:00.000000

Two unrelated bookkeeping changes:

1. The non-AKB partners now use single-character ``code`` values that
   match their ``prefix`` (P, N, O, U, X, J).  AKB stays ``AKB`` because
   that is the literal that appears in every client_code.
2. The ``GGX`` (AKB Xorazm filiali) partner is removed — the project no
   longer uses a Xorazm-only routing path; any code starting with ``G``
   that is not handled by the standard prefix table will fail loudly
   instead of silently routing to a Xorazm group.

Cascading deletes on ``partners.id`` clean up:
``partner_flight_aliases``, ``partner_payment_methods``,
``partner_static_data`` rows owned by the GGX partner.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p5e6f7g8h9i0"
down_revision: Union[str, None] = "p4a5k6b7p8q9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CODE_RENAMES: list[tuple[str, str]] = [
    ("PP", "P"),
    ("NN", "N"),
    ("OO", "O"),
    ("UZ", "U"),
    ("XB", "X"),
    ("JT", "J"),
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Drop GGX partner row (CASCADE removes its alias / method / static
    #    rows automatically).
    bind.execute(sa.text("DELETE FROM partners WHERE code = 'GGX'"))

    # 2. Shorten non-AKB partner codes to single characters.
    for old_code, new_code in _CODE_RENAMES:
        bind.execute(
            sa.text(
                "UPDATE partners SET code = :new WHERE code = :old"
            ),
            {"new": new_code, "old": old_code},
        )


def downgrade() -> None:
    bind = op.get_bind()

    for old_code, new_code in _CODE_RENAMES:
        bind.execute(
            sa.text(
                "UPDATE partners SET code = :old WHERE code = :new"
            ),
            {"new": new_code, "old": old_code},
        )

    # GGX is not re-inserted on downgrade — the data is lost.  Re-run the
    # original phase4 GGX migration to rebuild it if required.
