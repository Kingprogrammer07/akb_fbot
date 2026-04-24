"""add carousel_item_media table for feature multi-media support

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-05 00:00:00.000000

Why: Feature-type carousel items need to hold multiple media files
(up to 20 images, 20 GIFs, 5 videos).  A separate child table keeps the
parent row small and lets each entry be independently uploaded, ordered,
and deleted without touching the carousel_items row.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carousel_item_media",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "carousel_item_id",
            sa.Integer,
            sa.ForeignKey("carousel_items.id", ondelete="CASCADE"),
            nullable=False,
            comment="FK → carousel_items.id",
        ),
        sa.Column(
            "media_s3_key",
            sa.String(1024),
            nullable=True,
            comment="S3 object key; NULL for external-URL entries",
        ),
        sa.Column(
            "media_url",
            sa.String(1024),
            nullable=False,
            server_default="",
            comment="External URL (empty when media_s3_key is set)",
        ),
        sa.Column(
            "media_type",
            sa.String(20),
            nullable=False,
            comment="image | gif | video",
        ),
        sa.Column(
            "order",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Display order within the item (ascending)",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "media_type IN ('image', 'gif', 'video')",
            name="chk_carousel_item_media_type",
        ),
    )
    op.create_index(
        "ix_carousel_item_media_item_id",
        "carousel_item_media",
        ["carousel_item_id"],
    )
    op.create_index(
        "ix_carousel_item_media_item_order",
        "carousel_item_media",
        ["carousel_item_id", "order"],
    )


def downgrade() -> None:
    op.drop_index("ix_carousel_item_media_item_order", table_name="carousel_item_media")
    op.drop_index("ix_carousel_item_media_item_id", table_name="carousel_item_media")
    op.drop_table("carousel_item_media")
