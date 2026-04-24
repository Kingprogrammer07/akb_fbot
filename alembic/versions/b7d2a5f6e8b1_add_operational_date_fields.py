"""add_operational_date_fields

Revision ID: b7d2a5f6e8b1
Revises: c1b8617bbfb4
Create Date: 2026-04-14 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7d2a5f6e8b1"
down_revision = "c1b8617bbfb4"
branch_labels = None
depends_on = None


def upgrade():
    # flight_cargos table
    op.add_column(
        "flight_cargos",
        sa.Column(
            "is_sent_date",
            sa.DateTime(),
            nullable=True,
            comment="Date/time when cargo was sent to the client",
        ),
    )

    # client_transaction_data table
    op.add_column(
        "client_transaction_data",
        sa.Column(
            "fully_paid_date",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date/time when transaction became fully paid",
        ),
    )


def downgrade():
    op.drop_column("client_transaction_data", "fully_paid_date")
    op.drop_column("flight_cargos", "is_sent_date")
