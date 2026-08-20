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
from app.database.models import Payment
from app.services.payment import get_payment_provider
from app.services.payment_finalization import finalize_pending_payment, mark_payment_failed

logger = logging.getLogger(__name__)

router = APIRouter()


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

    bot = request.app.state.bot

    try:
        if webhook_status == 'success':
            await finalize_pending_payment(db, payment, bot)
        elif webhook_status == 'failed':
            await mark_payment_failed(db, payment)
        # 'pending' — не о чем сообщать, отвечаем 200 и ждём следующий колбэк.
    except Exception:
        logger.exception('Platega webhook: сбой при обработке payment_id=%s', payment.id)
        await db.rollback()
        return JSONResponse({'status': 'error', 'reason': 'processing_failed'}, status_code=400)

    return JSONResponse({'status': 'ok'})
