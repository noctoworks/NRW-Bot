"""add referral_milestone_reached to users

Revision ID: c7e3a9f1b4d6
Revises: b2c4d6e8f0a1
Create Date: 2026-08-19 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e3a9f1b4d6'
down_revision = 'b2c4d6e8f0a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('referral_milestone_reached', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('users', 'referral_milestone_reached')
