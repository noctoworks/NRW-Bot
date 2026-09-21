"""add is_active to promo_groups

Revision ID: 13a3c1d46134
Revises: 75ddf809d82b
Create Date: 2026-09-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '13a3c1d46134'
down_revision = '75ddf809d82b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('promo_groups', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column('promo_groups', 'is_active')
