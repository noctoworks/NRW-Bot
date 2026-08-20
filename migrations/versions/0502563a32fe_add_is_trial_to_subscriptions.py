"""add is_trial to subscriptions

Revision ID: 0502563a32fe
Revises: 00c6a7667609
Create Date: 2026-08-20 06:53:08.813559

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0502563a32fe'
down_revision = '00c6a7667609'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'subscriptions',
        sa.Column('is_trial', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('subscriptions', 'is_trial')
