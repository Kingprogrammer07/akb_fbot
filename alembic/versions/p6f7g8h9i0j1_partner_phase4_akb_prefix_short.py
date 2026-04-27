"""partner masking phase 4f: switch AKB partner prefix from 'AKB' to 'A'

Revision ID: p6f7g8h9i0j1
Revises: p5e6f7g8h9i0
Create Date: 2026-04-27 00:00:00.000000

The new short client_code format introduced by Phase 4e renders the
partner letter as a single ``A``: e.g. ``A02-14`` (Tashkent), ``ABG9``
(Buxoro G'ijduvon).  None of these codes start with the literal
``AKB`` so the previous 3-char prefix in the partners table never
matched.  Switch the AKB partner prefix back to the single character
``A`` — which uniquely identifies AKB clients because every other
partner uses a different single letter (P, N, O, U, X, J).

Legacy ``AKB570`` codes still start with ``A`` so the longest-prefix
match keeps working for them too.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p6f7g8h9i0j1"
down_revision: Union[str, None] = "p5e6f7g8h9i0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE partners SET prefix = 'A' WHERE code = 'AKB'")
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE partners SET prefix = 'AKB' WHERE code = 'AKB'")
    )
