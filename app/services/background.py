"""Фоновые задачи — см. §12 clone-architecture.md.

Шесть бесконечных циклов, запускаемые из main.py:
    expiry_checker_loop  — истечение подписок + напоминания за 3д/1д
    traffic_sync_loop    — синхронизация traffic_used_gb с Remnawave
    payment_poll_loop    — опрос статуса pending-платежей (только PAYMENTS_MODE=real);
                            страховка сверх вебхука (app/cabinet/webhooks.py), не
                            единственный путь подтверждения; заодно шлёт напоминание
                            о незавершённой оплате (см. диалог 2026-08-21)
    winback_loop         — одно сообщение тем, у кого подписка истекла и не продлена
    welcome_nudge_loop   — одно сообщение тем, кто зарегистрировался и не купил

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
from app.database.models import Payment, Subscription, User
from app.external.remnawave import get_remnawave_client
from app.services.notification_service import (
    notify_abandoned_payment,
    notify_subscription_expired,
    notify_subscription_expiring,
    notify_welcome_nudge,
    notify_winback,
)

logger = logging.getLogger(__name__)

# Задержки для автоматических триггеров (см. диалог 2026-08-21 "рассылки по
# событиям/напоминалки") — подобраны как разумные дефолты, не результат A/B-теста,
# можно менять без миграции (не хранятся в БД, только флаги "уже отправлено").
WINBACK_DELAY = timedelta(days=7)
WELCOME_NUDGE_DELAY = timedelta(hours=24)
ABANDONED_PAYMENT_DELAY = timedelta(hours=1)
# Пауза между отправками в winback/welcome_nudge/abandoned-payment циклах —
# Telegram ограничивает ~30 сообщений/сек глобально на бота, 50мс держит нас
# заметно ниже (~20/сек) даже если под критерий разом попадёт много юзеров
# (найдено вживую, см. диалог 2026-08-21: без паузы упёрлись в Flood control
# на 7422 сообщениях подряд при массовом прогоне по мигрированным юзерам).
# _safe_send сам разруливает отдельный TelegramRetryAfter одним ретраем — эта
# пауза не страховка от него, а профилактика, чтобы триггерить его пореже.
BULK_SEND_DELAY_SECONDS = 0.05


def _aware(dt: datetime) -> datetime:
    """SQLite (дефолтный DATABASE_URL для локальной разработки, см.
    .env.example) не сохраняет tzinfo у DateTime(timezone=True) колонок —
    объект возвращается naive, и прямое вычитание с datetime.now(timezone.utc)
    падает TypeError (найдено вживую тестом). На Postgres (прод/стейджинг)
    объект и так aware — replace() тогда no-op. Тот же приём, что в
    scripts/migrate_from_old_bot.py::_aware."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
                status, raw_response = await provider.check_payment_status_detailed(
                    payment.external_id, amount_kopeks=payment.amount_kopeks
                )
            except Exception:
                logger.warning('payment_poll_loop: не удалось опросить payment_id=%s', payment.id, exc_info=True)
                continue

            # Сохраняем свежий сырой ответ провайдера ДО финализации — тот же
            # identity-mapped объект Payment переиспользуется finalize_pending_payment/
            # mark_payment_failed внутри этой же сессии (см. их SELECT ... FOR
            # UPDATE по тому же id), так что правка попадёт в их же commit.
            if raw_response is not None:
                payment.provider_raw_response = raw_response

            try:
                if status == 'success':
                    await finalize_pending_payment(db, payment, bot)
                elif status == 'failed':
                    await mark_payment_failed(db, payment)
                elif (
                    not payment.abandoned_reminder_sent
                    and datetime.now(timezone.utc) - _aware(payment.created_at) >= ABANDONED_PAYMENT_DELAY
                ):
                    # Всё ещё pending спустя ABANDONED_PAYMENT_DELAY — не ошибка
                    # (payment.status не трогаем, поллинг продолжит проверять и
                    # дальше), просто разовое напоминание вернуться и завершить.
                    # Payment.user — не relationship (только user_id), в отличие
                    # от Subscription.user — db.get, а не db.refresh(attribute_names=).
                    payment_user = await db.get(User, payment.user_id)
                    if payment_user is not None and not payment_user.blocked_bot:
                        await notify_abandoned_payment(bot, telegram_id=payment_user.telegram_id)
                        await asyncio.sleep(BULK_SEND_DELAY_SECONDS)
                    payment.abandoned_reminder_sent = True
                    await db.commit()
                elif raw_response is not None:
                    # Ещё pending, до ABANDONED_PAYMENT_DELAY не дошли — коммитим
                    # отдельно, иначе правка provider_raw_response выше потеряется
                    # (сессия просто закроется без коммита в конце итерации).
                    await db.commit()
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


async def run_winback_once(bot: Bot) -> None:
    """Одна итерация win-back — см. диалог 2026-08-21. Кандидаты: подписка
    истекла (status='expired', выставляется run_expiry_check_once) не менее
    WINBACK_DELAY назад, письмо ещё не отправлено. winback_sent сбрасывается
    в False при следующем продлении (subscription_provisioning.py) — так что
    после повторного истечения win-back снова сработает."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Subscription).where(
                Subscription.status == 'expired',
                Subscription.winback_sent.is_(False),
                Subscription.end_date <= now - WINBACK_DELAY,
            )
        )
        for sub in result.scalars():
            await db.refresh(sub, attribute_names=['user'])
            if not sub.user.blocked_bot:
                await notify_winback(bot, telegram_id=sub.user.telegram_id)
                await asyncio.sleep(BULK_SEND_DELAY_SECONDS)
            sub.winback_sent = True

        await db.commit()


async def winback_loop(bot: Bot, interval_seconds: int = 3600) -> None:
    while True:
        try:
            await run_winback_once(bot)
        except Exception:
            logger.exception('winback_loop: сбой на итерации, продолжаем')
        await asyncio.sleep(interval_seconds)


async def run_welcome_nudge_once(bot: Bot) -> None:
    """Одна итерация приветственного nudge — см. диалог 2026-08-21. Кандидаты:
    зарегистрировался не менее WELCOME_NUDGE_DELAY назад, ещё не купил
    (подписки нет вообще ИЛИ она всё ещё триальная — is_trial=True), письмо
    ещё не отправлено. В отличие от winback/reminder-флагов — не сбрасывается
    никогда: nudge разовый за всю жизнь юзера, не за подписку."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User)
            .outerjoin(Subscription, Subscription.user_id == User.id)
            .where(
                User.welcome_nudge_sent.is_(False),
                User.blocked_bot.is_(False),
                User.created_at <= now - WELCOME_NUDGE_DELAY,
                (Subscription.id.is_(None)) | (Subscription.is_trial.is_(True)),
            )
        )
        for user in result.scalars().unique():
            await notify_welcome_nudge(bot, telegram_id=user.telegram_id)
            await asyncio.sleep(BULK_SEND_DELAY_SECONDS)
            user.welcome_nudge_sent = True

        await db.commit()


async def welcome_nudge_loop(bot: Bot, interval_seconds: int = 3600) -> None:
    while True:
        try:
            await run_welcome_nudge_once(bot)
        except Exception:
            logger.exception('welcome_nudge_loop: сбой на итерации, продолжаем')
        await asyncio.sleep(interval_seconds)
