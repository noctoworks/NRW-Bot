"""Фоновые задачи — см. §12 clone-architecture.md.

Три бесконечных цикла, запускаемые из main.py:
    expiry_checker_loop  — истечение подписок + напоминания за 3д/1д
    traffic_sync_loop    — синхронизация traffic_used_gb с Remnawave
    payment_poll_loop    — опрос статуса pending-платежей (только PAYMENTS_MODE=real);
                            страховка сверх вебхука (app/cabinet/webhooks.py), не
                            единственный путь подтверждения

Каждая "одна итерация" вынесена в отдельную testable-функцию (run_expiry_check_once,
run_traffic_sync_once), чтобы её можно было проверить напрямую в тесте, не гоняя
бесконечный while True.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import select

from app.database.database import AsyncSessionLocal
from app.database.models import Payment, Subscription
from app.external.remnawave import get_remnawave_client
from app.services.notification_service import notify_subscription_expired, notify_subscription_expiring

logger = logging.getLogger(__name__)


async def run_expiry_check_once(bot: Bot) -> None:
    """Одна итерация проверки истечения подписок + плановых напоминаний."""
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        # 1) истёкшие подписки -> expired + disable в Remnawave + уведомление
        result = await db.execute(
            select(Subscription).where(Subscription.status == 'active', Subscription.end_date <= now)
        )
        expired_subs = list(result.scalars())
        for sub in expired_subs:
            sub.status = 'expired'
            await db.refresh(sub, attribute_names=['user'])
            user = sub.user
            if user.remnawave_uuid:
                try:
                    await get_remnawave_client().disable_user(remnawave_uuid=user.remnawave_uuid)
                except Exception:
                    logger.warning('Не удалось отключить пользователя %s в Remnawave', user.remnawave_uuid, exc_info=True)
            await notify_subscription_expired(bot, telegram_id=user.telegram_id)

        # 2) напоминание за 3 дня
        result = await db.execute(
            select(Subscription).where(
                Subscription.status == 'active',
                Subscription.reminder_3d_sent.is_(False),
                Subscription.end_date > now + timedelta(days=1),
                Subscription.end_date <= now + timedelta(days=3),
            )
        )
        for sub in result.scalars():
            await db.refresh(sub, attribute_names=['user'])
            await notify_subscription_expiring(bot, telegram_id=sub.user.telegram_id, days_left=3)
            sub.reminder_3d_sent = True

        # 3) напоминание за 1 день
        result = await db.execute(
            select(Subscription).where(
                Subscription.status == 'active',
                Subscription.reminder_1d_sent.is_(False),
                Subscription.end_date > now,
                Subscription.end_date <= now + timedelta(days=1),
            )
        )
        for sub in result.scalars():
            await db.refresh(sub, attribute_names=['user'])
            await notify_subscription_expiring(bot, telegram_id=sub.user.telegram_id, days_left=1)
            sub.reminder_1d_sent = True

        await db.commit()


async def run_traffic_sync_once() -> None:
    """Одна итерация синхронизации traffic_used_gb с Remnawave для активных подписок."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Subscription).where(Subscription.status == 'active'))
        subs = list(result.scalars())
        client = get_remnawave_client()
        for sub in subs:
            await db.refresh(sub, attribute_names=['user'])
            user = sub.user
            if not user.remnawave_uuid:
                continue
            try:
                info = await client.get_subscription_info(remnawave_uuid=user.remnawave_uuid)
            except Exception:
                logger.warning('Не удалось получить traffic для %s из Remnawave', user.remnawave_uuid, exc_info=True)
                continue
            sub.traffic_used_gb = info.traffic_used_gb

        await db.commit()


async def expiry_checker_loop(bot: Bot, interval_seconds: int = 300) -> None:
    while True:
        try:
            await run_expiry_check_once(bot)
        except Exception:
            logger.exception('expiry_checker_loop: сбой на итерации, продолжаем')
        await asyncio.sleep(interval_seconds)


async def traffic_sync_loop(interval_seconds: int = 900) -> None:
    while True:
        try:
            await run_traffic_sync_once()
        except Exception:
            logger.exception('traffic_sync_loop: сбой на итерации, продолжаем')
        await asyncio.sleep(interval_seconds)


async def run_payment_poll_once(bot: Bot) -> None:
    """Одна итерация опроса pending-платежей (PAYMENTS_MODE=real, см. §12 и
    app/services/payment_finalization.py). С 2026-08-20 не единственный путь
    подтверждения — есть ещё вебхук (app/cabinet/webhooks.py, мгновенный,
    основной), этот поллинг — страховка на случай, если конкретный вебхук
    не долетел (сеть, наш сервер лежал в момент колбэка и т.п.), либо
    CABINET_ENABLED=false и вебхука вовсе нет."""
    from app.services.payment import get_payment_provider
    from app.services.payment_finalization import finalize_pending_payment, mark_payment_failed

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Payment).where(Payment.status == 'pending'))
        pending_payments = list(result.scalars())

        for payment in pending_payments:
            try:
                provider = get_payment_provider(payment.provider)
                status = await provider.check_payment_status(payment.external_id)
            except Exception:
                logger.warning('payment_poll_loop: не удалось опросить payment_id=%s', payment.id, exc_info=True)
                continue

            try:
                if status == 'success':
                    await finalize_pending_payment(db, payment, bot)
                elif status == 'failed':
                    await mark_payment_failed(db, payment)
            except Exception:
                logger.exception('payment_poll_loop: сбой при обработке payment_id=%s', payment.id)
                # Без явного rollback изменения, которые finalize_pending_payment
                # успел flush'нуть до падения (например payment.status='success' до
                # исключения в provision_or_extend_subscription), остались бы
                # "грязными" в ЭТОЙ ЖЕ сессии — и утекли бы в БД со следующим
                # успешным db.commit() дальше по циклу, для другого payment_id.
                await db.rollback()


async def payment_poll_loop(bot: Bot, interval_seconds: int = 600) -> None:
    """В PAYMENTS_MODE=stub опрашивать нечего — StubPaymentProvider всегда сразу
    возвращает success, зачисление происходит синхронно в момент оплаты."""
    from app.config import settings

    while True:
        try:
            if settings.PAYMENTS_MODE == 'real':
                await run_payment_poll_once(bot)
            # stub-режим: намеренно no-op.
        except Exception:
            logger.exception('payment_poll_loop: сбой на итерации, продолжаем')
        await asyncio.sleep(interval_seconds)
