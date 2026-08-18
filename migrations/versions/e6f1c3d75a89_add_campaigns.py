"""add campaigns and campaign_registrations

Revision ID: e6f1c3d75a89
Revises: d5e9b2a04c11
Create Date: 2026-08-18 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e6f1c3d75a89'
down_revision = 'd5e9b2a04c11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'campaigns',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('start_parameter', sa.String(length=64), nullable=False),
        sa.Column('bonus_type', sa.String(length=16), nullable=False),
        sa.Column('balance_bonus_kopeks', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('subscription_duration_days', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_campaigns_start_parameter', 'campaigns', ['start_parameter'], unique=True)

    op.create_table(
        'campaign_registrations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('campaign_id', 'user_id', name='uq_campaign_user'),
    )
    op.create_index('ix_campaign_registrations_campaign_id', 'campaign_registrations', ['campaign_id'])
    op.create_index('ix_campaign_registrations_user_id', 'campaign_registrations', ['user_id'])


def downgrade() -> None:
    op.drop_table('campaign_registrations')
    op.drop_table('campaigns')
