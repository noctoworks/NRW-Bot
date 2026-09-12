"""cisPay (СБП) — второй провайдер оплаты рядом с Platega (см. app/services/payment/platega.py
для образца структуры). Подключён по документации https://cispay.app/developers +
https://api.cispay.app/openapi.json.

В отличие от Platega (один непрозрачный paymentMethod-код, выбор
карта/СБП делает сама Platega на своей странице), у cisPay способ оплаты
фиксируется НАМИ при создании платежа. По требованию владельца бота
используется только SBP — customer_id обязателен для этого метода
(cisPay отклоняет SBP-платёж без идентификатора плательщика), поэтому
create_payment требует telegram_id (уже передаётся вызывающим кодом всем
провайдерам, см. app/handlers/subscription.py::purchase_or_renew_subscription).

Подтверждение — тем же двойным путём, что и Platega: вебхук
(app/cabinet/webhooks.py::cispay_webhook, мгновенно) как основной канал,
payment_poll_loop (app/services/background.py) — страховка на случай
не долетевшего колбэка.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from typing import Any

import httpx

from app.config import settings
from app.services.payment.base import CreatedPayment, PaymentProvider

logger = logging.getLogger(__name__)

_SUCCESS_STATUSES = {'PAID'}
_FAILED_STATUSES = {'FAILED', 'EXPIRED', 'REFUNDED'}
_DESCRIPTION_MAX_CHARS = 512  # PaymentCreateRequest.description: maxLength 512 (символы, не байты)


def _classify_status(status_raw: str) -> str:
    status = status_raw.upper()
    if status in _SUCCESS_STATUSES:
        return 'success'
    if status in _FAILED_STATUSES:
        return 'failed'
    return 'pending'


def _sanitize_description(description: str, max_chars: int = _DESCRIPTION_MAX_CHARS) -> str:
    cleaned = (description or '').strip()
    return cleaned[:max_chars]


class CisPayProvider(PaymentProvider):
    provider_name = 'cispay'

    def __init__(self) -> None:
        self.base_url = settings.CISPAY_BASE_URL.rstrip('/')

    def _headers(self) -> dict[str, str]:
        return {
            'X-Shop-ID': settings.CISPAY_SHOP_ID,
            'X-Api-Key': settings.CISPAY_API_KEY,
            'Content-Type': 'application/json',
        }

    async def _request(
        self, method: str, endpoint: str, *, json_data: dict[str, Any] | None = None, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f'{self.base_url}{endpoint}'
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, json=json_data, params=params, headers=self._headers())
        except httpx.HTTPError as error:
            logger.error('cisPay request failed: %s %s — %s', method, endpoint, error)
            raise RuntimeError(f'cisPay недоступна: {error}') from error

        if response.status_code >= 400:
            logger.error('cisPay API error %s on %s %s: %s', response.status_code, method, endpoint, response.text)
            raise RuntimeError(f'cisPay вернула ошибку {response.status_code}: {response.text[:200]}')

        if not response.text:
            return {}
        try:
            return response.json()
        except ValueError as error:
            raise RuntimeError(f'cisPay вернула не-JSON ответ: {response.text[:200]}') from error

    async def create_payment(
        self, *, user_id: int, amount_kopeks: int, description: str, bot=None, telegram_id: int | None = None
    ) -> CreatedPayment:
        # customer_id обязателен для SBP (см. докстринг модуля) — используем
        # telegram_id, а не user_id из своей БД, чтобы совпадало с тем, что
        # реально идентифицирует плательщика у нас в системе.
        if telegram_id is None:
            raise RuntimeError('cisPay (SBP) требует telegram_id для customer_id, получено None')

        body = {
            'amount': amount_kopeks,
            'currency': 'RUB',
            'order_id': f'nrw-{uuid.uuid4().hex}',
            'payment_method': 'SBP',
            'customer_id': str(telegram_id),
            'description': _sanitize_description(description),
        }

        response = await self._request('POST', '/payments', json_data=body)

        transaction_id = response.get('id')
        if not transaction_id:
            raise RuntimeError(f'cisPay не вернула id транзакции: {response}')

        return CreatedPayment(
            external_id=str(transaction_id),
            payment_url=response.get('payment_url'),
            status='pending',
            raw_response=response,
        )

    async def verify_webhook(self, payload: dict, headers: dict, *, raw_body: bytes | None = None) -> bool:
        """cisPay подписывает СЫРОЕ тело запроса HMAC-SHA256(X-Api-Key) в
        заголовке X-Signature (см. докстринг модуля) — в отличие от Platega,
        где колбэк просто повторяет свои auth-заголовки. Пересобранный из
        payload JSON не гарантированно совпадёт побайтово с тем, что подписала
        cisPay (порядок ключей/пробелы) — поэтому raw_body обязателен для
        настоящей проверки; без него считаем подпись непройденной, а не
        доверяем на слово. raw_body — keyword-only добавка поверх контракта
        PaymentProvider.verify_webhook (payload, headers), вызывается только
        из cispay_webhook (app/cabinet/webhooks.py), которому есть откуда его взять."""
        signature = headers.get('x-signature', '')
        if not signature or raw_body is None:
            return False
        expected = hmac.new(settings.CISPAY_API_KEY.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def check_payment_status(self, external_id: str, *, amount_kopeks: int | None = None) -> str:
        response = await self._request('GET', '/payments/status', params={'id': external_id})
        return _classify_status(str(response.get('status') or 'PENDING'))

    def parse_webhook_payload(self, payload: dict) -> tuple[str, str]:
        """(external_id, 'success'|'failed'|'pending') из тела вебхука — см.
        пример payload в докстринге модуля/документации: id/order_id/status/amount."""
        transaction_id = str(payload.get('id') or '').strip()
        status = _classify_status(str(payload.get('status') or ''))
        return transaction_id, status
