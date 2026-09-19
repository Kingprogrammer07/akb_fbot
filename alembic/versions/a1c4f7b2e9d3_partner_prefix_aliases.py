"""partner: extra client_code prefixes per partner (+ Q for Triton)

Adds ``partner_prefix_aliases`` so one partner can own several ``client_code``
prefixes while staying a single brand — one Telegram group, one card set, one
``foto_hisobot`` and one flight-mask namespace (masks are derived from
``partners.code``, not from the prefix).

Seeds the first alias: ``Q`` → Triton (``code='SYT'``).  Triton keeps its
primary ``SYT`` prefix, which already routes 701 historical cargo rows.

Revision ID: a1c4f7b2e9d3
Revises: 8d87d0c698bd
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1c4f7b2e9d3"
down_revision: Union[str, None] = "8d87d0c698bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SEED_ALIASES: list[tuple[str, str]] = [
    # (partner code, extra prefix)
    ("SYT", "Q"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "partner_prefix_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("prefix", sa.String(length=8), nullable=False),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("prefix", name="uq_partner_prefix_alias_prefix"),
        sa.CheckConstraint(
            "char_length(prefix) BETWEEN 1 AND 8",
            name="ck_partner_prefix_alias_len_range",
        ),
    )
    op.create_index(
        "ix_partner_prefix_aliases_partner_id",
        "partner_prefix_aliases",
        ["partner_id"],
    )

    bind = op.get_bind()
    for partner_code, prefix in _SEED_ALIASES:
        # A prefix already owned as a *primary* prefix would make resolution
        # ambiguous, so the seed refuses to create it rather than shadowing an
        # existing partner.  The resolver applies the same rule at runtime.
        owner = bind.execute(
            sa.text("SELECT code FROM partners WHERE upper(prefix) = :prefix"),
            {"prefix": prefix},
        ).scalar()
        if owner is not None:
            raise RuntimeError(
                f"cannot seed prefix alias {prefix!r} for {partner_code!r}: "
                f"partner {owner!r} already owns it as its primary prefix"
            )

        bind.execute(
            sa.text(
                "INSERT INTO partner_prefix_aliases (partner_id, prefix) "
                "SELECT id, :prefix FROM partners WHERE code = :code "
                "ON CONFLICT (prefix) DO NOTHING"
            ),
            {"prefix": prefix, "code": partner_code},
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_partner_prefix_aliases_partner_id",
        table_name="partner_prefix_aliases",
    )
    op.drop_table("partner_prefix_aliases")
