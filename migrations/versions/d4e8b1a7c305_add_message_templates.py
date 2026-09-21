"""add message_templates

Revision ID: d4e8b1a7c305
Revises: caa7bbb89896
Create Date: 2026-09-21 18:00:00.000000

Только добавляющая миграция (новая таблица) — откат безопасен. Пустая таблица = бот шлёт заводские тексты.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e8b1a7c305'
down_revision = 'caa7bbb89896'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'message_templates',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('template', sa.Text(), nullable=True),
        sa.Column('button_text', sa.String(length=64), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('message_templates')
