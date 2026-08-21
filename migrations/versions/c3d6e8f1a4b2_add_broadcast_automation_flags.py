"""add broadcast automation flags (winback, abandoned payment, welcome nudge)

Revision ID: c3d6e8f1a4b2
Revises: a8f4c1e9b3d7
Create Date: 2026-08-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d6e8f1a4b2'
down_revision = 'a8f4c1e9b3d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'subscriptions',
        sa.Column('winback_sent', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'payments',
        sa.Column('abandoned_reminder_sent', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'users',
        sa.Column('welcome_nudge_sent', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('users', 'welcome_nudge_sent')
    op.drop_column('payments', 'abandoned_reminder_sent')
    op.drop_column('subscriptions', 'winback_sent')
