"""add charged_amount_kopeks and merchant_revenue_kopeks to payments

Revision ID: caa7bbb89896
Revises: 13a3c1d46134
Create Date: 2026-09-16 00:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'caa7bbb89896'
down_revision = '13a3c1d46134'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('payments', sa.Column('charged_amount_kopeks', sa.BigInteger(), nullable=True))
    op.add_column('payments', sa.Column('merchant_revenue_kopeks', sa.BigInteger(), nullable=True))

    # Backfill из уже сохранённого provider_raw_response — cisPay кладёт туда
    # charged_amount/merchant_revenue при каждом create_payment/check_status/
    # вебхуке (см. диалог — "charged_amount": 24900, "merchant_revenue": 23904),
    # так что у существующих завершённых платежей cisPay эти цифры физически
    # уже лежат в JSON-блобе, просто не вынесены в отдельные колонки.
    # ->> 'x' на нечисловое/отсутствующее поле даёт NULL, а не ошибку — WHERE
    # ниже не обязателен для корректности, но экономит проход по остальным
    # провайдерам.
    # `?` (has-key) — оператор jsonb, а колонка типа json (см. Payment.provider_raw_response
    # в models.py) — используем ->> и проверяем на NULL вместо него, работает на обоих типах.
    op.execute(
        """
        UPDATE payments
        SET charged_amount_kopeks = (provider_raw_response ->> 'charged_amount')::bigint,
            merchant_revenue_kopeks = (provider_raw_response ->> 'merchant_revenue')::bigint
        WHERE provider = 'cispay'
          AND provider_raw_response ->> 'charged_amount' IS NOT NULL
          AND provider_raw_response ->> 'merchant_revenue' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column('payments', 'merchant_revenue_kopeks')
    op.drop_column('payments', 'charged_amount_kopeks')
