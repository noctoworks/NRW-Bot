"""Platega (СБП/карты) — основной платёжный провайдер, см. диалог: "берём логику
работы от Bedolaga". Реализация ОТЛОЖЕНА до появления реальных мерчант-ключей
(PAYMENTS_MODE=stub сейчас всегда перехватывает вызов раньше, чем он доходит сюда —
см. app/services/payment/__init__.py::get_payment_provider). Каркас оставлен, чтобы
структура совпадала с остальными провайдерами и подключение реальных ключей было
простой заменой NotImplementedError на реальные HTTP-вызовы, без переписывания вызывающего
кода (handlers/subscription.py, handlers/gift.py используют только PaymentProvider-интерфейс).
"""

from __future__ import annotations

from app.services.payment.base import CreatedPayment, PaymentProvider


class PlategaProvider(PaymentProvider):
    provider_name = 'platega'

    async def create_payment(self, *, user_id: int, amount_kopeks: int, description: str) -> CreatedPayment:
        # TODO(platega): POST /api/payments (или актуальный эндпоинт Platega) —
        # создание платежа, возврат payment_url для редиректа пользователя.
        raise NotImplementedError('Platega ещё не подключена — нет мерчант-ключей (см. диалог)')

    async def verify_webhook(self, payload: dict, headers: dict) -> bool:
        # TODO(platega): проверка подписи вебхука по документации Platega.
        raise NotImplementedError('Platega ещё не подключена — нет мерчант-ключей (см. диалог)')

    async def check_payment_status(self, external_id: str) -> str:
        # TODO(platega): GET-опрос статуса платежа по external_id.
        raise NotImplementedError('Platega ещё не подключена — нет мерчант-ключей (см. диалог)')
