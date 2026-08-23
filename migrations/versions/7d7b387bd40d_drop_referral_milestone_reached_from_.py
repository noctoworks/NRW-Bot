"""drop referral_milestone_reached from users

Revision ID: 7d7b387bd40d
Revises: c3d6e8f1a4b2
Create Date: 2026-08-23 12:56:39.965899

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7d7b387bd40d'
down_revision = 'c3d6e8f1a4b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Реф-программа с вехами (3/5/10/25/50 приглашённых) заменена на флэт-бонус
    # за каждого приглашённого (см. services/referral_service.py::
    # REFERRAL_INVITE_BONUS_DAYS, диалог 2026-08-23) — счётчик прогресса больше
    # не нужен, каждое приглашение начисляется независимо.
    op.drop_column('users', 'referral_milestone_reached')


def downgrade() -> None:
    op.add_column('users', sa.Column('referral_milestone_reached', sa.Integer(), nullable=False, server_default='0'))
