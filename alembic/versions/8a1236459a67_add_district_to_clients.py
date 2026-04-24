"""add_district_to_clients

Revision ID: 8a1236459a67
Revises: d1d04926f0a2
Create Date: 2026-02-20 22:17:59.634353

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a1236459a67'
down_revision: Union[str, None] = 'd1d04926f0a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    # 'clients' jadvaliga 'district' ustunini qo'shish
    op.add_column('clients', sa.Column('district', sa.String(length=128), nullable=True))


def downgrade():
    # Orqaga qaytarilganda 'district' ustunini o'chirib tashlash
    op.drop_column('clients', 'district')