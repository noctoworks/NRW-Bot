"""add provider_raw_response to payments

Revision ID: 75ddf809d82b
Revises: dba0f1887958
Create Date: 2026-09-01 08:30:00.000000

Down-revision перецеплен на dba0f1887958 (2026-09-01, продолжение фичи
"тело транзакции") — на момент создания файла dba0f1887958 (тикеты
поддержки) было незакоммиченным WIP, поэтому down_revision указывал на
7d7b387bd40d, чтобы не сломать деплой ссылкой на несуществующую в
git-archive ревизию. Тикеты закоммичены позже и стали новым head —
теперь можно (и нужно) починить цепочку на нормальную линейную.

Сверка выручки с личным кабинетом Platega (см. диалог 2026-09-01) показала
расхождение, которое пришлось объяснять через докер-логи прода — нет места,
где хранился бы последний сырой ответ провайдера по конкретному платежу.
Существующий Payment.raw_payload занят под контекст провижининга
(kind/tariff_id/period_days, см. app/services/payment_finalization.py) —
новое поле отдельное, только для сверки, бизнес-логика его не читает.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '75ddf809d82b'
down_revision = 'dba0f1887958'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('payments', sa.Column('provider_raw_response', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('payments', 'provider_raw_response')
