"""Мгновенный успех — см. диалог: 'Платежи на первом этапе — сначала стаб'.

Позволяет разработать и протестировать всю цепочку зачисления баланса/подписки
без единого внешнего платёжного ключа. Переключение на реальные провайдеры —
через PAYMENTS_MODE=real в .env, без изменения вызывающего кода.
"""

from __future__ import annotations

import uuid

from app.services.payment.base import CreatedPayment, PaymentProvider


class StubPaymentProvider(PaymentProvider):
    def __init__(self, provider_name: str = 'stub') -> None:
        self.provider_name = provider_name

    async def create_payment(
        self, *, user_id: int, amount_kopeks: int, description: str, bot=None, telegram_id=None
    ) -> CreatedPayment:
        return CreatedPayment(
            external_id=f'stub-{uuid.uuid4().hex[:12]}',
            payment_url=None,  # вызывающий код должен сразу считать платёж успешным в stub-режиме
            status='success',
        )

    async def verify_webhook(self, payload: dict, headers: dict) -> bool:
        return True

    async def check_payment_status(self, external_id: str, *, amount_kopeks: int | None = None) -> str:
        return 'success'
