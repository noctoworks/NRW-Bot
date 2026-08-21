"""add platega_subscription_id to subscriptions

Revision ID: a8f4c1e9b3d7
Revises: 0502563a32fe
Create Date: 2026-08-21 05:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8f4c1e9b3d7'
down_revision = '0502563a32fe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'subscriptions',
        sa.Column('platega_subscription_id', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('subscriptions', 'platega_subscription_id')
