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
from typing import Any

import httpx

from app.config import settings
from app.services.payment.base import CreatedPayment, PaymentProvider

logger = logging.getLogger(__name__)

_SUCCESS_STATUSES = {'CONFIRMED'}
_FAILED_STATUSES = {'FAILED', 'CANCELED', 'EXPIRED'}
_DESCRIPTION_MAX_BYTES = 64


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

        return CreatedPayment(external_id=str(transaction_id), payment_url=payment_url, status='pending')

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

    async def check_payment_status(self, external_id: str) -> str:
        # Тот же выбор версии, что и в create_payment (endpoint) — раньше здесь был
        # всегда захардкожен v1-путь, независимо от PLATEGA_API_VERSION. При
        # PLATEGA_API_VERSION=v2 платёж создавался по v2-контракту, а опрашивался
        # по v1-эндпоинту — на реальном мерчанте это могло не подтверждать платежи
        # вообще (см. ревью).
        endpoint = f'/v2/transaction/{external_id}' if self.api_version == 'v2' else f'/transaction/{external_id}'
        response = await self._request('GET', endpoint)
        return _classify_status(str(response.get('status') or 'PENDING'))

    def parse_webhook_payload(self, payload: dict) -> tuple[str, str]:
        """(external_id, 'success'|'failed'|'pending') из тела вебхука. Поле id
        транзакции в колбэке называется 'id' (см. process_platega_webhook
        оригинального бота) — не то же самое, что 'transactionId'/'id' в ответе
        create_payment, но принимаем оба варианта на случай расхождения версий API."""
        transaction_id = str(payload.get('id') or payload.get('transactionId') or payload.get('transaction_id') or '').strip()
        status = _classify_status(str(payload.get('status') or ''))
        return transaction_id, status
