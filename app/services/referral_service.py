"""Контракт между subscription.py (вызывает после каждой успешной оплаты) и
referral.py (владеет реализацией). См. §9.6 clone-architecture.md: 25% фиксированно,
с КАЖДОЙ оплаты приглашённого (не только первой).

TODO(agent:referral-promo): реализовать тело функций.
"""

from __future__ import annotations

import secrets
import string

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Payment


def generate_referral_code(length: int = 8) -> str:
    """Читаемый код для реферальной ссылки (не для промокода — тот отдельно)."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


async def credit_referral_earning(db: AsyncSession, payment: Payment) -> None:
    """Вызывается ПОСЛЕ фиксации успешного платежа (topup или subscription_payment).

    Логика: найти payment.user; если у него есть referred_by_id — начислить
    REFERRAL_PERCENT от payment.amount_kopeks на баланс реферера, создать
    ReferralEarning(source=purchase|topup), не бросать исключение наружу
    (реферальная программа не должна ломать основной платёжный флоу — только
    логировать ошибку, если что-то пошло не так).
    """
    raise NotImplementedError
