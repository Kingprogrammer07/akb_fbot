"""merge heads: partner prefix aliases + payment event admin id split

Revision ID: c3f8a2d6e1b4
Revises: a1c4f7b2e9d3, a1c2e3f4b5d6
Create Date: 2026-09-11 12:00:00.000000

Both parents branch from 8d87d0c698bd and change unrelated tables
(``partner_prefix_aliases`` and ``client_payment_events``), so they can be
applied in either order.  This revision only joins the two heads.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "c3f8a2d6e1b4"
down_revision: Union[str, Sequence[str], None] = ("a1c4f7b2e9d3", "a1c2e3f4b5d6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema change — joins two independent heads."""


def downgrade() -> None:
    """No schema change — splits back into the two heads."""
