"""partner masking phase 1: tables + wipe + widened client codes

Revision ID: p1a2r3t4n5e6
Revises: e2f3a4b5c6d7
Create Date: 2026-04-25 00:00:00.000000

This migration introduces the Partner masking infrastructure:

1. Wipes all client-data-bearing tables (clients, cargos, transactions,
   payment cards, etc.) so the new code generator starts on a clean slate.
   ``CASCADE`` is used to follow any indirect foreign-key references.
2. Widens ``clients.client_code`` and ``clients.extra_code`` from
   ``VARCHAR(10)`` to ``VARCHAR(20)`` to accommodate the new
   ``A{region}-{district}/{seq}`` format.
3. Creates four new tables: ``partners``, ``partner_flight_aliases``,
   ``partner_payment_methods``, ``partner_static_data``.
4. Seeds the seven partners (AKB + 6 external) and a paired
   ``partner_static_data`` row for each.

DESTRUCTIVE — backup the database before running.  The downgrade
restores the schema but cannot recover the wiped data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p1a2r3t4n5e6"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that hold client-derived rows.  Order does not matter because we
# use CASCADE; we just need to enumerate every root table whose data must
# be reset.  Tables that may not exist in older deployments are guarded
# inside the loop so a missing table is not a fatal error.
_TABLES_TO_WIPE: list[str] = [
    "clients",
    "client_extra_passport",
    "client_transactions",
    "client_payment_events",
    "cargo_items",
    "flight_cargos",
    "expected_flight_cargos",
    "delivery_requests",
    "partner_shipment_temp",
    "cargo_delivery_proofs",
    "payment_cards",
    "user_payment_cards",
    "session_logs",
    "broadcast_messages",
    "analytics_events",
    "notifications",
    "stats_daily_clients",
    "stats_daily_cargo",
    "stats_daily_payments",
]


_PARTNER_SEED: list[dict] = [
    {"code": "AKB", "display_name": "AKB",          "prefix": "A", "is_dm_partner": True},
    {"code": "PP",  "display_name": "Navo cargo",   "prefix": "P", "is_dm_partner": False},
    {"code": "NN",  "display_name": "Jon cargo",    "prefix": "N", "is_dm_partner": False},
    {"code": "OO",  "display_name": "Oneway cargo", "prefix": "O", "is_dm_partner": False},
    {"code": "UZ",  "display_name": "Uztez",        "prefix": "U", "is_dm_partner": False},
    {"code": "XB",  "display_name": "Habib",        "prefix": "X", "is_dm_partner": False},
    {"code": "JT",  "display_name": "Jet",          "prefix": "J", "is_dm_partner": False},
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── 1. Wipe data ────────────────────────────────────────────────────────
    for table in _TABLES_TO_WIPE:
        if table in existing_tables:
            op.execute(sa.text(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE'))

    # ── 2. Widen client code columns ───────────────────────────────────────
    op.alter_column(
        "clients",
        "client_code",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    op.alter_column(
        "clients",
        "extra_code",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=True,
    )

    # ── 3. New tables ──────────────────────────────────────────────────────
    op.create_table(
        "partners",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=1), nullable=False),
        sa.Column("group_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("is_dm_partner", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("code", name="uq_partners_code"),
        sa.UniqueConstraint("prefix", name="uq_partners_prefix"),
        sa.CheckConstraint(
            "char_length(prefix) = 1",
            name="ck_partner_prefix_len_1",
        ),
    )

    op.create_table(
        "partner_flight_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("real_flight_name", sa.String(length=100), nullable=False),
        sa.Column("mask_flight_name", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("partner_id", "real_flight_name", name="uq_pfa_partner_real"),
        sa.UniqueConstraint("partner_id", "mask_flight_name", name="uq_pfa_partner_mask"),
    )
    op.create_index(
        "ix_pfa_partner_mask",
        "partner_flight_aliases",
        ["partner_id", "mask_flight_name"],
    )
    op.create_index(
        "ix_pfa_partner_real",
        "partner_flight_aliases",
        ["partner_id", "real_flight_name"],
    )

    op.create_table(
        "partner_payment_methods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("method_type", sa.String(length=8), nullable=False),
        sa.Column("card_number", sa.String(length=20), nullable=True),
        sa.Column("card_holder", sa.String(length=128), nullable=True),
        sa.Column("link_label", sa.String(length=64), nullable=True),
        sa.Column("link_url", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("weight", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "method_type IN ('card', 'link')",
            name="ck_ppm_method_type",
        ),
        sa.CheckConstraint(
            "(method_type = 'card' AND card_number IS NOT NULL "
            "AND card_holder IS NOT NULL "
            "AND link_label IS NULL AND link_url IS NULL) "
            "OR (method_type = 'link' AND link_label IS NOT NULL "
            "AND link_url IS NOT NULL "
            "AND card_number IS NULL AND card_holder IS NULL)",
            name="ck_ppm_fields_match_type",
        ),
        sa.CheckConstraint("weight >= 1", name="ck_ppm_weight_positive"),
    )
    op.create_index(
        "ix_partner_payment_methods_partner_id",
        "partner_payment_methods",
        ["partner_id"],
    )

    op.create_table(
        "partner_static_data",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("foto_hisobot", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("partner_id", name="uq_partner_static_data_partner_id"),
    )
    op.create_index(
        "ix_partner_static_data_partner_id",
        "partner_static_data",
        ["partner_id"],
    )

    # ── 4. Seed partners + paired static data ──────────────────────────────
    partners_table = sa.table(
        "partners",
        sa.column("code", sa.String),
        sa.column("display_name", sa.String),
        sa.column("prefix", sa.String),
        sa.column("is_dm_partner", sa.Boolean),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        partners_table,
        [
            {**row, "is_active": True}
            for row in _PARTNER_SEED
        ],
    )

    # Insert one ``partner_static_data`` row per seeded partner via SELECT —
    # this avoids hardcoding the partner ids assigned by the sequence.
    op.execute(
        sa.text(
            "INSERT INTO partner_static_data (partner_id, foto_hisobot) "
            "SELECT id, '' FROM partners"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_partner_static_data_partner_id",
        table_name="partner_static_data",
    )
    op.drop_table("partner_static_data")

    op.drop_index(
        "ix_partner_payment_methods_partner_id",
        table_name="partner_payment_methods",
    )
    op.drop_table("partner_payment_methods")

    op.drop_index("ix_pfa_partner_real", table_name="partner_flight_aliases")
    op.drop_index("ix_pfa_partner_mask", table_name="partner_flight_aliases")
    op.drop_table("partner_flight_aliases")

    op.drop_table("partners")

    op.alter_column(
        "clients",
        "extra_code",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=True,
    )
    op.alter_column(
        "clients",
        "client_code",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=True,
    )
