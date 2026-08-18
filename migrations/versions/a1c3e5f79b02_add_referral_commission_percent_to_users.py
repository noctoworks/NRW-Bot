"""add referral_commission_percent to users

Revision ID: a1c3e5f79b02
Revises: 8b1a98ef6217
Create Date: 2026-08-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c3e5f79b02'
down_revision = '8b1a98ef6217'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('referral_commission_percent', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'referral_commission_percent')
