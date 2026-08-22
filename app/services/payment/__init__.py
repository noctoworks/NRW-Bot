"""Фабрика провайдера оплаты: stub или real по PAYMENTS_MODE (см. §7 clone-architecture.md)."""

from __future__ import annotations

from app.config import settings
from app.services.payment.base import PaymentProvider
from app.services.payment.stub import StubPaymentProvider


def get_payment_provider(name: str) -> PaymentProvider:
    """`name` — 'platega'|'stars'|'ton'. В stub-режиме все ведут себя одинаково —
    мгновенный успех, чтобы бизнес-логику можно было тестировать без внешних ключей.

    Platega — основной провайдер (СБП/карты), см. диалог: логика/структура по образцу
    Bedolaga, но пока БЕЗ реальных ключей (PAYMENTS_MODE=stub) — подключим API, когда
    появится реальный мерчант-доступ."""
    if settings.PAYMENTS_MODE == 'stub':
        return StubPaymentProvider(provider_name=name)

    if name == 'platega':
        from app.services.payment.platega import PlategaProvider

        return PlategaProvider()
    if name == 'stars':
        from app.services.payment.stars import StarsProvider

        return StarsProvider()
    if name == 'ton':
        from app.services.payment.ton import TonProvider

        return TonProvider()

    raise ValueError(f'Неизвестный платёжный провайдер: {name}')
