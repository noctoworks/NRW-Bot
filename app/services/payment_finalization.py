"""Доводит до конца платёж, подтверждённый асинхронно (payment_poll_loop, см.
app/services/background.py) — то есть созданный как pending в handlers/subscription.py
или handlers/gift.py, когда провайдер (PAYMENTS_MODE=real) не подтверждает оплату
мгновенно. Контекст, необходимый для выдачи подписки/подарка, хранится в
Payment.raw_payload (kind/tariff_id/period_days) — см. места создания pending Payment.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Payment, Tariff, Transaction, User
from app.services.gift_service import create_gift_code
from app.services.notification_service import notify_gift_code_ready, notify_payment_success
from app.services.referral_service import credit_referral_earning
from app.services.subscription_provisioning import provision_or_extend_subscription

logger = logging.getLogger(__name__)


async def finalize_pending_payment(db: AsyncSession, payment: Payment, bot: Bot) -> None:
    # payment_poll_loop (интервал по умолчанию 600с) и scripts/poll_payments_once.py
    # (ручной параллельный запуск, см. диалог) могут выбрать один и тот же pending-
    # платёж одновременно. with_for_update() + повторная проверка status=='pending'
    # ПОСЛЕ захвата блокировки строки (реально работает на Postgres в проде, SQLite
    # это условие молча игнорирует) закрывают это окно: второй процесс, дождавшись
    # снятия блокировки первым, увидит уже не-pending статус и тихо выйдет — вместо
    # повторной выдачи подписки/подарка и повторного реферального начисления.
    locked = await db.execute(select(Payment).where(Payment.id == payment.id).with_for_update())
    payment = locked.scalar_one_or_none()
    if payment is None or payment.status != 'pending':
        return

    raw_payload = payment.raw_payload or {}
    kind = raw_payload.get('kind')
    tariff_id = raw_payload.get('tariff_id')
    period_days = raw_payload.get('period_days')

    user = await db.get(User, payment.user_id)
    tariff = await db.get(Tariff, tariff_id) if tariff_id is not None else None

    if user is None or tariff is None or period_days is None or kind not in ('subscription', 'gift'):
        logger.error(
            'finalize_pending_payment: не могу доделать payment_id=%s (user=%s tariff=%s kind=%s) — '
            'оставляю pending, требуется ручной разбор',
            payment.id,
            user,
            tariff,
            kind,
        )
        return

    # Провижининг (Remnawave/создание gift-кода) — ДО того, как платёж помечается
    # success. Если это упадёт, исключение уходит наружу к вызывающему коду
    # (run_payment_poll_once), который обязан откатить сессию — иначе payment.status
    # так и останется 'pending' в БД, и следующий цикл поллинга/ручной скрипт
    # попробуют доделать выдачу снова, вместо того чтобы навсегда зафиксировать
    # "успешный" платёж без реально выданной подписки/подарка (тот же класс бага,
    # что был найден в handlers/subscription.py::cb_confirm_purchase).
    if kind == 'subscription':
        await provision_or_extend_subscription(db, user=user, tariff=tariff, period_days=period_days, is_trial=False)
    else:
        gift_code = await create_gift_code(db, tariff=tariff, period_days=period_days, gifter=user)

    payment.status = 'success'
    if payment.transaction_id is not None:
        transaction = await db.get(Transaction, payment.transaction_id)
        if transaction is not None:
            transaction.status = 'completed'

    if kind == 'subscription':
        description = f'Подписка «{tariff.name}» на {period_days} дн.'
        try:
            await notify_payment_success(
                bot, telegram_id=user.telegram_id, amount_kopeks=payment.amount_kopeks, description=description
            )
        except Exception:
            logger.exception('notify_payment_success упал (не блокирует выдачу подписки)')
    else:
        bot_username = settings.BOT_USERNAME or '<укажите_BOT_USERNAME>'
        link = f'https://t.me/{bot_username}?start=gift_{gift_code.code}'
        try:
            await notify_gift_code_ready(bot, telegram_id=user.telegram_id, link=link)
        except Exception:
            logger.exception('notify_gift_code_ready упал (не блокирует создание подарочного кода)')

    try:
        await credit_referral_earning(db, payment)
    except Exception:
        logger.exception('credit_referral_earning упал (не блокирует подтверждение платежа)')

    await db.commit()
