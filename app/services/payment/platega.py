"""Platega (СБП/карты) — основной платёжный провайдер. HTTP-детали (эндпоинты,
заголовки, маппинг статусов) портированы из PlategaService оригинального бота
(remnawave-bedolaga-telegram-bot/app/services/platega_service.py). Подтверждение
идёт ДВУМЯ путями одновременно (см. диалог, 2026-08-20): вебхук
(app/cabinet/webhooks.py::platega_webhook, мгновенно) как основной, и
payment_poll_loop (app/services/background.py, раз в 10 минут) как страховка на
случай, если конкретный вебхук не долетел/наш сервер был недоступен в момент
колбэка — Platega вебхуки не ретраит бесконечно.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.services.payment.base import CreatedPayment, PaymentProvider

logger = logging.getLogger(__name__)

_SUCCESS_STATUSES = {'CONFIRMED'}
_FAILED_STATUSES = {'FAILED', 'CANCELED', 'EXPIRED'}
_DESCRIPTION_MAX_BYTES = 64

# Автосписание СБП (см. https://docs.platega.io/ раздел "Подписки", диалог
# 2026-08-21). paymentMethod=6 — фиксированный код именно для подписок, ОТ
# ОБЫЧНЫХ платежей (settings.PLATEGA_PAYMENT_METHOD_CODE) не зависит.
_SUBSCRIPTION_PAYMENT_METHOD = 6
# Автоплатёж всегда ежемесячный по цене 30-дневного периода тарифа —
# используется и в handlers/subscription.py (toggle), и в
# app/cabinet/webhooks.py (продление при списании), см. диалог 2026-08-21:
# интервал у Platega фиксируется один раз при создании подписки и не
# совпадает с произвольными периодами тарифа (30/90/180/360 дней).
AUTOPAY_PERIOD_DAYS = 30
# Статусы жизненного цикла подписки (не путать с _SUCCESS_STATUSES/_FAILED_STATUSES
# выше — те про статус ОДНОЙ транзакции, эти — про подписку целиком).
_SUBSCRIPTION_ACTIVE_STATUSES = {'SUBSCRIPTION_ACTIVATED'}
_SUBSCRIPTION_DEAD_STATUSES = {'SUBSCRIPTION_CANCELLED', 'SUBSCRIPTION_FAILED', 'SUBSCRIPTION_PAST_DUE'}


@dataclass
class CreatedSubscription:
    subscription_id: str
    confirm_url: str


def _ci_get(payload: dict, key: str) -> Any:
    """Platega шлёт callback'и по подпискам в PascalCase (Id/Status/SubscriptionId),
    обычные платёжные — в lowercase (id/status) — портировано из оригинального
    бота, там та же несогласованность отмечена как "arrives in camelCase while
    spec examples are PascalCase". Регистронезависимый поиск, чтобы не зависеть
    от того, какой вариант реально прилетит."""
    key_lower = key.lower()
    for k, v in payload.items():
        if k.lower() == key_lower:
            return v
    return None


def _classify_status(status_raw: str) -> str:
    """Общая классификация для check_payment_status (поллинг) И вебхука
    (app/cabinet/webhooks.py) — одно место для _SUCCESS_STATUSES/_FAILED_STATUSES,
    чтобы два пути подтверждения платежа не разъехались в трактовке статусов."""
    status = status_raw.upper()
    if status in _SUCCESS_STATUSES:
        return 'success'
    if status in _FAILED_STATUSES:
        return 'failed'
    return 'pending'


def _sanitize_description(description: str, max_bytes: int = _DESCRIPTION_MAX_BYTES) -> str:
    """Обрезает описание с учётом байтового лимита Platega (см. референс)."""
    cleaned = (description or '').strip()
    encoded = cleaned.encode('utf-8')
    if len(encoded) <= max_bytes:
        return cleaned

    trimmed = encoded[:max_bytes]
    while trimmed:
        try:
            return trimmed.decode('utf-8')
        except UnicodeDecodeError:
            trimmed = trimmed[:-1]
    return ''


class PlategaProvider(PaymentProvider):
    provider_name = 'platega'

    def __init__(self) -> None:
        self.base_url = settings.PLATEGA_BASE_URL.rstrip('/')
        self.api_version = settings.PLATEGA_API_VERSION

    def _headers(self) -> dict[str, str]:
        return {
            'X-MerchantId': settings.PLATEGA_MERCHANT_ID,
            'X-Secret': settings.PLATEGA_SECRET_KEY,
            'Content-Type': 'application/json',
        }

    async def _request(self, method: str, endpoint: str, *, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f'{self.base_url}{endpoint}'
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, json=json_data, headers=self._headers())
        except httpx.HTTPError as error:
            logger.error('Platega request failed: %s %s — %s', method, endpoint, error)
            raise RuntimeError(f'Platega недоступна: {error}') from error

        if response.status_code >= 400:
            logger.error('Platega API error %s on %s %s: %s', response.status_code, method, endpoint, response.text)
            raise RuntimeError(f'Platega вернула ошибку {response.status_code}: {response.text[:200]}')

        if not response.text:
            return {}
        try:
            return response.json()
        except ValueError as error:
            raise RuntimeError(f'Platega вернула не-JSON ответ: {response.text[:200]}') from error

    async def create_payment(
        self, *, user_id: int, amount_kopeks: int, description: str, bot=None, telegram_id=None
    ) -> CreatedPayment:
        endpoint = '/v2/transaction/process' if self.api_version == 'v2' else '/transaction/process'
        body = {
            'paymentMethod': settings.PLATEGA_PAYMENT_METHOD_CODE,
            'paymentDetails': {
                'amount': round(amount_kopeks / 100, 2),
                'currency': 'RUB',
            },
            'description': _sanitize_description(description),
        }

        response = await self._request('POST', endpoint, json_data=body)

        transaction_id = response.get('transactionId') or response.get('id')
        if not transaction_id:
            raise RuntimeError(f'Platega не вернула id транзакции: {response}')

        payment_url = response.get('redirect') or response.get('url')

        return CreatedPayment(
            external_id=str(transaction_id), payment_url=payment_url, status='pending', raw_response=response
        )

    async def verify_webhook(self, payload: dict, headers: dict) -> bool:
        # Platega аутентифицирует колбэк ТЕМИ ЖЕ заголовками, что и мы её (см.
        # _headers выше) — не отдельной HMAC-подписью тела. headers ключи уже
        # приведены к нижнему регистру вызывающим кодом (app/cabinet/webhooks.py),
        # ASGI и так отдаёт их в lowercase, здесь — для явности контракта.
        # compare_digest — не ради тайминг-атак с этим конкретным секретом
        # (риск нулевой), а просто чтобы не городить == для двух строк отдельно.
        merchant_id = headers.get('x-merchantid', '')
        secret = headers.get('x-secret', '')
        return bool(
            hmac.compare_digest(merchant_id, settings.PLATEGA_MERCHANT_ID)
            and hmac.compare_digest(secret, settings.PLATEGA_SECRET_KEY)
        )

    async def check_payment_status(self, external_id: str, *, amount_kopeks: int | None = None) -> str:
        # Тот же выбор версии, что и в create_payment (endpoint) — раньше здесь был
        # всегда захардкожен v1-путь, независимо от PLATEGA_API_VERSION. При
        # PLATEGA_API_VERSION=v2 платёж создавался по v2-контракту, а опрашивался
        # по v1-эндпоинту — на реальном мерчанте это могло не подтверждать платежи
        # вообще (см. ревью).
        endpoint = f'/v2/transaction/{external_id}' if self.api_version == 'v2' else f'/transaction/{external_id}'
        response = await self._request('GET', endpoint)
        return _classify_status(str(response.get('status') or 'PENDING'))

    async def check_payment_status_detailed(
        self, external_id: str, *, amount_kopeks: int | None = None
    ) -> tuple[str, dict | None]:
        """Переопределяет базовую реализацию, чтобы вернуть и статус, и сырое
        тело ответа ОДНИМ запросом (не дублировать HTTP-вызов check_payment_status
        выше — см. диалог 2026-09-01, сверка со статистикой Platega)."""
        endpoint = f'/v2/transaction/{external_id}' if self.api_version == 'v2' else f'/transaction/{external_id}'
        response = await self._request('GET', endpoint)
        return _classify_status(str(response.get('status') or 'PENDING')), response

    async def export_transactions(self, *, since: datetime, until: datetime) -> list[dict[str, Any]]:
        """POST /transaction/export/json (см. диалог 2026-09-01, "решить вопрос
        по транзакциям" — сверка нашего /admin/transactions со стороной Platega,
        нашли эндпоинт по документации https://docs.platega.io/, не было в коде
        раньше). Возвращает СЫРЫЕ записи Platega (recordId/createdAt/amount/
        currencyCode/status/paymentMethod/description/payload) — сопоставление
        recordId с нашим Payment.external_id делает вызывающий код
        (app/cabinet/admin_routes.py), эта функция ничего не знает о нашей БД."""
        endpoint = '/v2/transaction/export/json' if self.api_version == 'v2' else '/transaction/export/json'
        body = {
            'from': since.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            'to': until.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            'timeZoneId': 'UTC',
        }
        response = await self._request('POST', endpoint, json_data=body)
        return response if isinstance(response, list) else []

    def parse_webhook_payload(self, payload: dict) -> tuple[str, str]:
        """(external_id, 'success'|'failed'|'pending') из тела вебхука. Поле id
        транзакции в колбэке называется 'id' (см. process_platega_webhook
        оригинального бота) — не то же самое, что 'transactionId'/'id' в ответе
        create_payment, но принимаем оба варианта на случай расхождения версий API."""
        transaction_id = str(payload.get('id') or payload.get('transactionId') or payload.get('transaction_id') or '').strip()
        status = _classify_status(str(payload.get('status') or ''))
        return transaction_id, status

    def is_subscription_webhook(self, payload: dict) -> bool:
        """И списание по подписке, и смена статуса подписки прилетают на тот же
        /platega-webhook, что и обычные платежи (см. process_platega_subscription_callback
        оригинального бота — тот же путь, отдельная ветка по paymentMethod/статусу).
        Признаки: paymentMethod=6, есть SubscriptionId, либо статус с префиксом
        SUBSCRIPTION_ — любого из трёх достаточно, реальный колбэк может не
        прислать все сразу."""
        payment_method = _ci_get(payload, 'paymentMethod')
        if payment_method is not None and int(payment_method) == _SUBSCRIPTION_PAYMENT_METHOD:
            return True
        if _ci_get(payload, 'subscriptionId'):
            return True
        status = str(_ci_get(payload, 'status') or '')
        return status.upper().startswith('SUBSCRIPTION_')

    def parse_subscription_webhook(self, payload: dict) -> dict[str, Any]:
        """Разбирает ОБА вида колбэка подписки (списание и смена статуса — см.
        is_subscription_webhook) в одну структуру. kind='status', если Status
        начинается с SUBSCRIPTION_ (см. _SUBSCRIPTION_ACTIVE/DEAD_STATUSES),
        иначе kind='charge' (CONFIRMED/CANCELED — статус ОДНОЙ попытки списания,
        не подписки целиком)."""
        status_raw = str(_ci_get(payload, 'status') or '').upper()
        subscription_id = str(_ci_get(payload, 'subscriptionId') or _ci_get(payload, 'id') or '').strip()
        is_status_event = status_raw.startswith('SUBSCRIPTION_')
        return {
            'kind': 'status' if is_status_event else 'charge',
            'subscription_id': subscription_id,
            'status_raw': status_raw,
            'charge_id': str(_ci_get(payload, 'id') or '').strip(),
            'amount_kopeks': int((_ci_get(payload, 'amount') or 0)) * 100 if not is_status_event else None,
            # Статус подписки как факт (для kind='status'): 'active'/'dead'/'unknown' —
            # 'unknown' на будущее, если Platega заведёт статус, которого мы не знаем,
            # чтобы не тихо трактовать его как активный.
            'subscription_alive': (status_raw in _SUBSCRIPTION_ACTIVE_STATUSES) if is_status_event else None,
        }

    async def create_subscription(self, *, amount_kopeks: int, description: str) -> CreatedSubscription:
        """Автосписание раз в месяц (interval=3 — см. диалог 2026-08-21: у Platega
        интервал фиксируется один раз при создании подписки и не совпадает с
        произвольными периодами тарифа 30/90/180/360 дней, поэтому автоплатёж
        всегда по цене 30-дневного периода, ежемесячно, независимо от того, какой
        период юзер покупал изначально). Возвращает confirm_url — пользователь
        должен его открыть и подтвердить привязку счёта в банк-приложении (окно
        30 минут), сама подписка станет активной только после этого (см. вебхук
        SUBSCRIPTION_ACTIVATED, не сразу после этого запроса)."""
        body = {
            'paymentMethod': _SUBSCRIPTION_PAYMENT_METHOD,
            'paymentDetails': {
                'amount': round(amount_kopeks / 100, 2),
                'currency': 'RUB',
                'interval': '3',
            },
            'description': _sanitize_description(description),
        }
        response = await self._request('POST', '/transaction/process', json_data=body)

        subscription_id = response.get('transactionId')
        confirm_url = response.get('redirect')
        if not subscription_id or not confirm_url:
            raise RuntimeError(f'Platega не вернула transactionId/redirect для подписки: {response}')

        return CreatedSubscription(subscription_id=str(subscription_id), confirm_url=str(confirm_url))

    async def cancel_subscription(self, subscription_id: str) -> None:
        """Идемпотентно (см. докстринг эндпоинта) — повторный вызов на уже
        отменённую подписку не ошибка."""
        await self._request('POST', f'/subscription/{subscription_id}/cancel')
