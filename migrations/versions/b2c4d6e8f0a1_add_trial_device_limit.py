"""add trial device limit override to tariffs, set default trial config

Revision ID: b2c4d6e8f0a1
Revises: a3b6e0f2c8d4
Create Date: 2026-08-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c4d6e8f0a1'
down_revision = 'a3b6e0f2c8d4'
branch_labels = None
depends_on = None


tariffs = sa.table(
    'tariffs',
    sa.column('is_active', sa.Boolean),
    sa.column('trial_enabled', sa.Boolean),
    sa.column('trial_period_days', sa.Integer),
    sa.column('trial_traffic_limit_gb', sa.BigInteger),
    sa.column('trial_device_limit', sa.Integer),
)


def upgrade() -> None:
    op.add_column('tariffs', sa.Column('trial_device_limit', sa.Integer(), nullable=True))

    # Продуктовое решение: новый пользователь сразу получает пробный период —
    # 5 дней, лимит устройств 3, лимит трафика 25 ГБ (см. диалог с владельцем бота).
    # Применяем к активным тарифам — там, откуда start.py берёт триал (get_active_tariff).
    op.execute(
        tariffs.update()
        .where(tariffs.c.is_active.is_(True))
        .values(
            trial_enabled=True,
            trial_period_days=5,
            trial_traffic_limit_gb=25,
            trial_device_limit=3,
        )
    )


def downgrade() -> None:
    op.drop_column('tariffs', 'trial_device_limit')
