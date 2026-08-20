"""CryptoBot (@CryptoBot / @send, Crypto Pay API) — оплата в крипте с конвертацией
из рублей на стороне CryptoBot (currency_type=fiat), чтобы не тащить свой курс
крипта/рубль — в отличие от Stars (см. app/services/payment/stars.py), где курс
задаём сами (STARS_RATE_KOPEKS), потому что Stars не имеет собственного понятия
"фиатный эквивалент".

Официальный REST API: https://help.crypt.bot/crypto-pay-api — эндпоинты и коды
статусов сверены по документации (не по стороннему бот-референсу, готового
клиента под кошельком/схемой в проекте не было).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.services.payment.base import CreatedPayment, PaymentProvider

logger = logging.getLogger(__name__)

CRYPTOBOT_BASE_URL = 'https://pay.crypt.bot/api'

_SUCCESS_STATUSES = {'PAID'}
_FAILED_STATUSES = {'EXPIRED'}


class CryptoBotProvider(PaymentProvider):
    provider_name = 'cryptobot'

    def _headers(self) -> dict[str, str]:
        return {'Crypto-Pay-API-Token': settings.CRYPTOBOT_API_TOKEN, 'Content-Type': 'application/json'}

    async def _request(self, method: str, endpoint: str, *, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f'{CRYPTOBOT_BASE_URL}{endpoint}'
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, json=json_data, headers=self._headers())
        except httpx.HTTPError as error:
            logger.error('CryptoBot request failed: %s %s — %s', method, endpoint, error)
            raise RuntimeError(f'CryptoBot недоступен: {error}') from error

        if response.status_code >= 400:
            logger.error('CryptoBot API error %s on %s %s: %s', response.status_code, method, endpoint, response.text)
            raise RuntimeError(f'CryptoBot вернул ошибку {response.status_code}: {response.text[:200]}')

        try:
            data = response.json()
        except ValueError as error:
            raise RuntimeError(f'CryptoBot вернул не-JSON ответ: {response.text[:200]}') from error

        # Crypto Pay API оборачивает любой ответ в {"ok": bool, "result"/"error": ...}
        if not data.get('ok'):
            raise RuntimeError(f'CryptoBot API error: {data.get("error")}')
        return data.get('result') or {}

    async def create_payment(
        self, *, user_id: int, amount_kopeks: int, description: str, bot=None, telegram_id=None
    ) -> CreatedPayment:
        body = {
            'currency_type': 'fiat',
            'fiat': 'RUB',
            'amount': f'{amount_kopeks / 100:.2f}',
            'description': description[:1024],
            # accepted_assets не передаём — пусть CryptoBot предложит все, что
            # держит у себя сам мерчант (управляется в настройках @CryptoBot).
        }
        result = await self._request('POST', '/createInvoice', json_data=body)

        invoice_id = result.get('invoice_id')
        if not invoice_id:
            raise RuntimeError(f'CryptoBot не вернул invoice_id: {result}')

        payment_url = result.get('bot_invoice_url') or result.get('pay_url')
        return CreatedPayment(external_id=str(invoice_id), payment_url=payment_url, status='pending')

    async def verify_webhook(self, payload: dict, headers: dict) -> bool:
        # Вебхук не подключён — см. Platega, тот же выбор (нет публичного домена
        # на момент разработки), подтверждение через payment_poll_loop.
        raise NotImplementedError('CryptoBot webhook не подключён — используется поллинг')

    async def check_payment_status(self, external_id: str) -> str:
        result = await self._request('GET', f'/getInvoices?invoice_ids={external_id}')
        items = result.get('items') or []
        if not items:
            return 'pending'

        status = str(items[0].get('status') or 'active').upper()
        if status in _SUCCESS_STATUSES:
            return 'success'
        if status in _FAILED_STATUSES:
            return 'failed'
        return 'pending'
