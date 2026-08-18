"""Platega (СБП/карты) — основной платёжный провайдер. HTTP-детали (эндпоинты,
заголовки, маппинг статусов) портированы из PlategaService оригинального бота
(remnawave-bedolaga-telegram-bot/app/services/platega_service.py), но без
вебхук-роутов и их отдельной модели PlategaPayment — здесь подтверждение идёт
через поллинг (app/services/background.py::payment_poll_loop), см. диалог: нет
публичного URL для вебхука.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.services.payment.base import CreatedPayment, PaymentProvider

logger = logging.getLogger(__name__)

_SUCCESS_STATUSES = {'CONFIRMED'}
_FAILED_STATUSES = {'FAILED', 'CANCELED', 'EXPIRED'}
_DESCRIPTION_MAX_BYTES = 64


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

    async def create_payment(self, *, user_id: int, amount_kopeks: int, description: str) -> CreatedPayment:
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
        # Вебхук не подключён в этом заходе — нет публичного URL/домена (см. диалог).
        # Подтверждение платежа идёт через payment_poll_loop (check_payment_status).
        raise NotImplementedError('Platega webhook не подключён — используется поллинг')

    async def check_payment_status(self, external_id: str) -> str:
        response = await self._request('GET', f'/transaction/{external_id}')
        status = str(response.get('status') or 'PENDING').upper()

        if status in _SUCCESS_STATUSES:
            return 'success'
        if status in _FAILED_STATUSES:
            return 'failed'
        return 'pending'
