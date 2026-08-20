"""Telegram Stars — единственный провайдер, который не ходит ни к какому внешнему
API: счёт создаётся прямо в чате пользователя через Bot.send_invoice, оплата
подтверждается Telegram'ом асинхронно (pre_checkout_query -> successful_payment),
а не поллингом внешнего статуса. См. handlers/stars_payment.py — там pre_checkout_query
и successful_payment, здесь только формирование счёта.

currency='XTR', provider_token='' (пустая строка, не None — обязательное требование
Bot API именно для Stars, в отличие от обычных провайдеров) — см. официальную
документацию Bot API, раздел Payments/Stars.
"""

from __future__ import annotations

import uuid

from aiogram.types import LabeledPrice

from app.config import settings
from app.services.payment.base import CreatedPayment, PaymentProvider


class StarsProvider(PaymentProvider):
    provider_name = 'stars'

    async def create_payment(
        self, *, user_id: int, amount_kopeks: int, description: str, bot=None, telegram_id=None
    ) -> CreatedPayment:
        if bot is None or telegram_id is None:
            raise RuntimeError('StarsProvider.create_payment требует bot и telegram_id')

        stars = max(1, round(amount_kopeks / settings.STARS_RATE_KOPEKS))
        # payload — единственная нить, связывающая будущий successful_payment с этим
        # Payment: Telegram вернёт его как есть в message.successful_payment.invoice_payload.
        external_id = f'stars-{uuid.uuid4().hex}'

        await bot.send_invoice(
            chat_id=telegram_id,
            title='Оплата',
            description=description[:255],
            payload=external_id,
            currency='XTR',
            prices=[LabeledPrice(label=description[:32] or 'Оплата', amount=stars)],
            provider_token='',
        )

        return CreatedPayment(external_id=external_id, payment_url=None, status='pending')

    async def verify_webhook(self, payload: dict, headers: dict) -> bool:
        raise NotImplementedError('У Stars нет вебхука — подтверждение через successful_payment')

    async def check_payment_status(self, external_id: str) -> str:
        # payment_poll_loop подберёт этот платёж, только если пользователь никогда
        # не оплатит инвойс (а successful_payment-хендлер и не прилетит) — сам
        # факт оплаты сюда не приходит вообще, Telegram не даёт API для опроса
        # статуса конкретного Stars-инвойса. Возвращаем pending бессрочно;
        # реальное подтверждение — только через handlers/stars_payment.py.
        return 'pending'
