"""Контракт между subscription.py (вызывает после каждой успешной оплаты) и
referral.py (владеет реализацией). См. §9.6 clone-architecture.md: 25% фиксированно,
с КАЖДОЙ оплаты приглашённого (не только первой).

TODO(agent:referral-promo): реализовать тело функций.
"""

from __future__ import annotations

import logging
import secrets
import string

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Payment, ReferralEarning, Transaction, User
from app.services.notification_service import notify_referral_bonus
from app.services.subscription_provisioning import provision_or_extend_subscription

logger = logging.getLogger(__name__)

# Виральность (см. диалог 2026-08-23: "пригласил друга -> сразу 3 дня") —
# флэт-бонус рефереру за КАЖДОГО приглашённого, сразу при регистрации (не за
# оплаты — это отдельно уже покрыто REFERRAL_PERCENT/credit_referral_earning).
# Заменяет прежнюю систему вех 3/5/10/25/50 приглашённых.
REFERRAL_INVITE_BONUS_DAYS = 3


def generate_referral_code(length: int = 8) -> str:
    """Читаемый код для реферальной ссылки (не для промокода — тот отдельно)."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


async def credit_referral_earning(db: AsyncSession, payment: Payment, bot: Bot | None = None) -> None:
    """Вызывается ПОСЛЕ фиксации успешного платежа (topup или subscription_payment).

    Логика: найти payment.user; если у него есть referred_by_id — начислить
    от payment.amount_kopeks на баланс реферера процент, равный
    referrer.referral_commission_percent (если задан персонально админом,
    см. /cabinet/admin/users/{id}/referral-commission) или settings.REFERRAL_PERCENT
    по умолчанию, создать ReferralEarning(source=purchase|topup) + Transaction
    (type='referral_reward' — иначе начисление не попадает в историю транзакций
    реферала, см. ревью) и уведомить реферера (если передан bot), не бросать
    исключение наружу (реферальная программа не должна ломать основной
    платёжный флоу — только логировать ошибку, если что-то пошло не так).
    """
    try:
        if payment.status != 'success':
            return
        if payment.provider == 'balance':
            # Оплата собственным балансом (см. handlers/subscription.py) не заводит
            # в систему новых денег — это уже начисленные ранее рефералки/бонусы,
            # которые пользователь просто тратит. Начислять с неё ещё одну
            # комиссию рефереру значило бы платить комиссию с денег, которые
            # бизнес никогда реально не получал.
            return

        result = await db.execute(select(User).where(User.id == payment.user_id))
        buyer = result.scalar_one_or_none()
        if buyer is None or buyer.referred_by_id is None:
            return

        result = await db.execute(select(User).where(User.id == buyer.referred_by_id))
        referrer = result.scalar_one_or_none()
        if referrer is None or referrer.is_blocked:
            return

        percent = referrer.referral_commission_percent
        if percent is None:
            percent = settings.REFERRAL_PERCENT
        # Округляем ДО ЦЕЛОГО РУБЛЯ, всегда вверх — в пользу реферера (см.
        # apply_discount в pricing_service.py: то же правило, симметрично —
        # там пользователь платит меньше, тут реферер получает больше,
        # дробных копеек на балансе появляться больше не должно).
        # payment.amount_kopeks * percent / 10000 == точная сумма в рублях;
        # -(-a // b) — целочисленный ceil(a / b) без float.
        amount_kopeks = -(-(payment.amount_kopeks * percent) // 10000) * 100
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
        db.add(
            Transaction(
                user_id=referrer.id,
                type='referral_reward',
                amount_kopeks=amount_kopeks,
                status='completed',
                description=f'Реферальная комиссия с покупки user_id={buyer.id}',
            )
        )
        await db.flush()

        if bot is not None:
            try:
                await notify_referral_bonus(bot, telegram_id=referrer.telegram_id, amount_kopeks=amount_kopeks)
            except Exception:
                logger.exception('notify_referral_bonus упал (не блокирует начисление)')
    except Exception:
        logger.exception('credit_referral_earning failed for payment_id=%s', getattr(payment, 'id', None))


async def credit_referral_invite_bonus(db: AsyncSession, referrer: User, bot: Bot | None = None) -> None:
    """Вызывается один раз сразу после регистрации нового пользователя по
    реф-ссылке (см. handlers/start.py::cb_accept_rules) — начисляет рефереру
    флэт REFERRAL_INVITE_BONUS_DAYS дней подписки за это приглашение, без
    требования, чтобы приглашённый что-то оплатил (это отдельно уже покрыто
    REFERRAL_PERCENT/credit_referral_earning). Не бросает исключение наружу —
    бонус за приглашение не должен ломать саму регистрацию нового пользователя."""
    try:
        # with_for_update() — свежее значение is_blocked, если админ заблокировал
        # реферера прямо в этот момент (тот же приём, что был в предыдущей
        # версии этой функции для порогов).
        locked = await db.execute(select(User).where(User.id == referrer.id).with_for_update())
        referrer = locked.scalar_one()

        if referrer.is_blocked:
            return

        # Локальный импорт — get_active_tariff живёт в handlers/subscription.py,
        # который сам импортирует этот модуль (credit_referral_earning) на
        # уровне модуля; импорт на верхнем уровне здесь создал бы цикл
        # (тот же приём уже используется в handlers/start.py).
        from app.handlers.subscription import get_active_tariff

        tariff = await get_active_tariff(db)
        if tariff is None:
            logger.warning('credit_referral_invite_bonus: нет активного тарифа, бонус не начислен referrer_id=%s', referrer.id)
            return

        await provision_or_extend_subscription(db, user=referrer, tariff=tariff, period_days=REFERRAL_INVITE_BONUS_DAYS)
        await db.flush()

        if bot is not None:
            try:
                from app.services.notification_service import notify_referral_invite_bonus

                await notify_referral_invite_bonus(bot, telegram_id=referrer.telegram_id, bonus_days=REFERRAL_INVITE_BONUS_DAYS)
            except Exception:
                logger.exception('notify_referral_invite_bonus failed for referrer_id=%s', referrer.id)
    except Exception:
        logger.exception('credit_referral_invite_bonus failed for referrer_id=%s', getattr(referrer, 'id', None))
