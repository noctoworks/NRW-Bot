"""add trial squad/traffic overrides to tariffs

Revision ID: f7a2c9d4e1b6
Revises: e6f1c3d75a89
Create Date: 2026-08-18 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a2c9d4e1b6'
down_revision = 'e6f1c3d75a89'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tariffs', sa.Column('trial_squad_uuids', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('tariffs', sa.Column('trial_traffic_limit_gb', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('tariffs', 'trial_traffic_limit_gb')
    op.drop_column('tariffs', 'trial_squad_uuids')
