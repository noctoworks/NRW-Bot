"""Контракт между subscription.py (вызывает после каждой успешной оплаты) и
referral.py (владеет реализацией). См. §9.6 clone-architecture.md: 25% фиксированно,
с КАЖДОЙ оплаты приглашённого (не только первой).

TODO(agent:referral-promo): реализовать тело функций.
"""

from __future__ import annotations

import logging
import secrets
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Payment, ReferralEarning, Transaction, User

logger = logging.getLogger(__name__)


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
    try:
        if payment.status != 'success':
            return

        result = await db.execute(select(User).where(User.id == payment.user_id))
        buyer = result.scalar_one_or_none()
        if buyer is None or buyer.referred_by_id is None:
            return

        result = await db.execute(select(User).where(User.id == buyer.referred_by_id))
        referrer = result.scalar_one_or_none()
        if referrer is None:
            return

        amount_kopeks = (payment.amount_kopeks * settings.REFERRAL_PERCENT) // 100
        if amount_kopeks <= 0:
            return

        source = 'topup'
        if payment.transaction_id is not None:
            tx_result = await db.execute(select(Transaction).where(Transaction.id == payment.transaction_id))
            transaction = tx_result.scalar_one_or_none()
            if transaction is not None and transaction.type != 'topup':
                source = 'purchase'

        referrer.balance_kopeks += amount_kopeks
        db.add(
            ReferralEarning(
                user_id=referrer.id,
                source_user_id=buyer.id,
                payment_id=payment.id,
                amount_kopeks=amount_kopeks,
                source=source,
            )
        )
        await db.flush()
    except Exception:
        logger.exception('credit_referral_earning failed for payment_id=%s', getattr(payment, 'id', None))
