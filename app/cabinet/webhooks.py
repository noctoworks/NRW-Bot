"""Платёжные вебхуки — /platega-webhook и т.д., БЕЗ префикса /cabinet/*. Живут
в том же FastAPI-процессе/порту, что и остальной Cabinet API (см.
app/cabinet/app.py), поэтому требуют CABINET_ENABLED=true; отдельного сервера
под вебхуки нет.

Путь /platega-webhook — не наш выбор, а уже готовая инфраструктура (см. диалог,
2026-08-20): на проде Caddy на admin.nocto.online уже проксирует именно этот
путь (и /webhook, /tribute-webhook, /cryptobot-webhook, /health — see
Caddyfile) на порт 8080 контейнера, который сейчас занят старым ботом
(remnawave_bot, remnawave-bedolaga-telegram-bot-bot) — NRW-Bot туда ЕЩЁ НЕ
задеплоен. Значение путей взято из PLATEGA_WEBHOOK_PATH старого бота (см.
app/config.py оригинала) — Caddy настроен под конкретно эту строку, не
"/cabinet/webhooks/platega", которая была здесь раньше по ошибке (никакой
реальной инфраструктуры под неё не было). Когда NRW-Bot займёт порт 8080
вместо старого бота, вебхук заработает без единой правки Caddyfile — если имя
пути когда-нибудь понадобится сменить, начинать нужно оттуда, а не отсюда.

Основной путь подтверждения платежа теперь этот вебхук (мгновенный), а не
payment_poll_loop (app/services/background.py, раз в 10 минут) — тот остаётся
страховкой на случай пропущенного колбэка (наш сервер был недоступен в момент
события, сетевой сбой и т.п.; Platega не ретраит вебхук бесконечно). Оба пути
идут через finalize_pending_payment/mark_payment_failed
(app/services/payment_finalization.py), которые блокируют строку Payment
(SELECT ... FOR UPDATE) и перепроверяют status=='pending' — так что обработка
одного и того же платежа вебхуком и поллингом почти одновременно безопасна,
выдача подписки/реферальное начисление не задвоятся.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cabinet.deps import get_db
from app.database.models import Payment, Subscription, Transaction
from app.services.notification_service import (
    notify_autopay_activated,
    notify_autopay_charge_failed,
    notify_autopay_stopped,
    notify_payment_success,
)
from app.services.payment import get_payment_provider
from app.services.payment.platega import AUTOPAY_PERIOD_DAYS
from app.services.payment_finalization import finalize_pending_payment, mark_payment_failed
from app.services.referral_service import credit_referral_earning
from app.services.subscription_provisioning import provision_or_extend_subscription

logger = logging.getLogger(__name__)

router = APIRouter()


async def _handle_subscription_webhook(db: AsyncSession, bot, provider, payload: dict) -> JSONResponse:
    parsed = provider.parse_subscription_webhook(payload)
    subscription_id = parsed['subscription_id']
    if not subscription_id:
        logger.warning('Platega subscription webhook: нет subscriptionId, keys=%s', sorted(payload) if isinstance(payload, dict) else None)
        return JSONResponse({'status': 'error', 'reason': 'no_subscription_id'}, status_code=400)

    result = await db.execute(
        select(Subscription).where(Subscription.platega_subscription_id == subscription_id).with_for_update()
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        # Не 200 — до отправки этого колбэка мы уже должны были сохранить
        # platega_subscription_id при включении автоплатежа (см. handlers).
        # Если его ещё нет — либо гонка (наш commit не успел), либо баг;
        # 400 просит Platega повторить, а не тихо теряет событие.
        logger.warning('Platega subscription webhook: Subscription не найдена для subscription_id=%s', subscription_id)
        return JSONResponse({'status': 'error', 'reason': 'subscription_not_found'}, status_code=400)

    await db.refresh(subscription, attribute_names=['user', 'tariff'])
    user = subscription.user

    if parsed['kind'] == 'status':
        if parsed['subscription_alive'] is True:
            await notify_autopay_activated(bot, telegram_id=user.telegram_id)
        elif parsed['subscription_alive'] is False:
            subscription.autopay_enabled = False
            subscription.platega_subscription_id = None
            await notify_autopay_stopped(bot, telegram_id=user.telegram_id)
        # subscription_alive is None (незнакомый статус) — ничего не трогаем,
        # только залогируем ниже и подтвердим 200 (не наш баг решать за Platega).
        else:
            logger.warning('Platega subscription webhook: неизвестный статус подписки %s', parsed['status_raw'])
        await db.commit()
        return JSONResponse({'status': 'ok'})

    # kind == 'charge' — списание по уже активной подписке.
    charge_id = parsed['charge_id']
    if parsed['status_raw'] == 'CONFIRMED':
        if charge_id:
            existing = await db.execute(select(Payment.id).where(Payment.provider == 'platega', Payment.external_id == charge_id))
            if existing.scalar_one_or_none() is not None:
                logger.info('Platega subscription webhook: charge_id=%s уже обработан, повтор колбэка', charge_id)
                return JSONResponse({'status': 'ok'})

        await provision_or_extend_subscription(
            db, user=user, tariff=subscription.tariff, period_days=AUTOPAY_PERIOD_DAYS, is_trial=False
        )

        transaction = Transaction(
            user_id=user.id,
            type='subscription_payment',
            amount_kopeks=parsed['amount_kopeks'],
            status='completed',
            description=f'Автоплатёж — «{subscription.tariff.name}»',
        )
        db.add(transaction)
        await db.flush()

        payment = Payment(
            user_id=user.id,
            transaction_id=transaction.id,
            provider='platega',
            external_id=charge_id or subscription_id,
            amount_kopeks=parsed['amount_kopeks'],
            status='success',
            raw_payload={'kind': 'autopay', 'subscription_id': subscription_id},
            provider_raw_response=payload,
        )
        db.add(payment)
        await db.flush()

        try:
            await notify_payment_success(
                bot,
                telegram_id=user.telegram_id,
                amount_kopeks=parsed['amount_kopeks'],
                description=f'Автопродление «{subscription.tariff.name}»',
            )
        except Exception:
            logger.exception('notify_payment_success (автоплатёж) упал (не блокирует продление)')

        try:
            await credit_referral_earning(db, payment, bot=bot)
        except Exception:
            logger.exception('credit_referral_earning (автоплатёж) упал (не блокирует продление)')

        await db.commit()
    elif parsed['status_raw'] == 'CANCELED':
        # Разовая неудача списания — сама подписка Platega переводит в PastDue
        # ОТДЕЛЬНЫМ status-колбэком (см. выше), здесь просто уведомляем; текущий
        # доступ не трогаем — подписка действует до уже оплаченной даты.
        await notify_autopay_charge_failed(bot, telegram_id=user.telegram_id)
        await db.commit()

    return JSONResponse({'status': 'ok'})


@router.get('/platega-webhook')
async def platega_health() -> JSONResponse:
    """Platega дёргает URL до сохранения при добавлении вебхука в личном
    кабинете — без 200 на GET сохранить адрес не даст."""
    return JSONResponse({'status': 'ok', 'service': 'platega_webhook'})


@router.post('/platega-webhook')
async def platega_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # Verification ping: Platega при первом сохранении URL шлёт запрос без
    # авторизационных заголовков и без тела — это не подделка колбэка, а
    # проверка доступности эндпоинта (см. process_platega_webhook в
    # оригинальном боте). Обычная auth-проверка ниже отклонила бы такой запрос
    # 401-м и Platega не дала бы сохранить адрес вебхука.
    if not headers.get('x-merchantid') and not headers.get('x-secret') and not raw_body.strip():
        logger.info('Platega webhook: verification ping (нет заголовков, пустое тело)')
        return JSONResponse({'status': 'ok'})

    provider = get_payment_provider('platega')

    try:
        payload = json.loads(raw_body) if raw_body.strip() else {}
    except json.JSONDecodeError:
        logger.warning('Platega webhook: невалидный JSON')
        return JSONResponse({'status': 'error', 'reason': 'invalid_json'}, status_code=400)

    if not await provider.verify_webhook(payload, headers):
        logger.warning('Platega webhook: не прошёл проверку заголовков (X-MerchantId/X-Secret)')
        return JSONResponse({'status': 'error', 'reason': 'unauthorized'}, status_code=401)

    # is_subscription_webhook/parse_subscription_webhook — методы только у
    # PlategaProvider (автоплатёж — фича конкретно Platega, не часть общего
    # PaymentProvider), в PAYMENTS_MODE=stub их нет вовсе — hasattr вместо
    # isinstance, чтобы не тащить сюда импорт конкретного класса провайдера.
    if hasattr(provider, 'is_subscription_webhook') and provider.is_subscription_webhook(payload):
        return await _handle_subscription_webhook(db, request.app.state.bot, provider, payload)

    external_id, webhook_status = provider.parse_webhook_payload(payload)
    if not external_id:
        logger.warning('Platega webhook: нет id транзакции в payload, keys=%s', sorted(payload) if isinstance(payload, dict) else None)
        return JSONResponse({'status': 'error', 'reason': 'no_transaction_id'}, status_code=400)

    result = await db.execute(select(Payment).where(Payment.provider == 'platega', Payment.external_id == external_id))
    payment = result.scalar_one_or_none()
    if payment is None:
        # 400, а не 200 — по спецификациям большинства провайдеров не-200
        # означает "повторите позже", это здесь уместно: колбэк вполне может
        # долететь раньше, чем наш собственный INSERT в Payment зафиксируется
        # (create_payment коммитит ДО получения payment_url в некоторых
        # путях) — повторная попытка от Platega такую гонку сгладит сама.
        logger.warning('Platega webhook: Payment не найден для external_id=%s', external_id)
        return JSONResponse({'status': 'error', 'reason': 'payment_not_found'}, status_code=400)

    payment.provider_raw_response = payload
    bot = request.app.state.bot

    try:
        if webhook_status == 'success':
            await finalize_pending_payment(db, payment, bot)
        elif webhook_status == 'failed':
            await mark_payment_failed(db, payment)
        else:
            # 'pending' — не о чем сообщать по существу платежа, отвечаем 200 и
            # ждём следующий колбэк; коммитим явно, иначе правка
            # provider_raw_response выше потеряется при закрытии сессии без
            # изменений статуса (get_db не коммитит сам по себе).
            await db.commit()
    except Exception:
        logger.exception('Platega webhook: сбой при обработке payment_id=%s', payment.id)
        await db.rollback()
        return JSONResponse({'status': 'error', 'reason': 'processing_failed'}, status_code=400)

    return JSONResponse({'status': 'ok'})
