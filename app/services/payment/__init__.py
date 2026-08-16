"""Фабрика провайдера оплаты: stub или real по PAYMENTS_MODE (см. §7 clone-architecture.md)."""

from __future__ import annotations

from app.config import settings
from app.services.payment.base import PaymentProvider
from app.services.payment.stub import StubPaymentProvider


def get_payment_provider(name: str) -> PaymentProvider:
    """`name` — 'stars'|'yookassa'|'cryptobot'. В stub-режиме все три ведут себя одинаково —
    мгновенный успех, чтобы бизнес-логику можно было тестировать без внешних ключей."""
    if settings.PAYMENTS_MODE == 'stub':
        return StubPaymentProvider(provider_name=name)

    if name == 'yookassa':
        from app.services.payment.yookassa import YooKassaProvider

        return YooKassaProvider()
    if name == 'cryptobot':
        from app.services.payment.cryptobot import CryptoBotProvider

        return CryptoBotProvider()
    if name == 'stars':
        from app.services.payment.stars import StarsProvider

        return StarsProvider()

    raise ValueError(f'Неизвестный платёжный провайдер: {name}')
