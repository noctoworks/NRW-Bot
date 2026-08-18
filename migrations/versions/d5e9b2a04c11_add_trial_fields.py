"""add trial fields to tariffs and users

Revision ID: d5e9b2a04c11
Revises: c4d8a1f23e77
Create Date: 2026-08-18 00:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5e9b2a04c11'
down_revision = 'c4d8a1f23e77'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tariffs', sa.Column('trial_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('tariffs', sa.Column('trial_period_days', sa.Integer(), nullable=False, server_default='3'))
    op.add_column('users', sa.Column('trial_used', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('users', 'trial_used')
    op.drop_column('tariffs', 'trial_period_days')
    op.drop_column('tariffs', 'trial_enabled')
