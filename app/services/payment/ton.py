"""TON Connect — оплата прямым переводом на кошелёк (см. app/config.py, диалог
2026-08-21). У TON нет ни вебхука, ни "провайдера", который сам подтверждает
сумму/факт оплаты как Platega — есть только сам блокчейн. Схема:

1. create_payment генерирует уникальный текстовый комментарий (external_id) и
   сумму в нанотонах по курсу TON_RATE_KOPEKS. Фронтенд (NRW-MiniApp) через
   @tonconnect/ui-react формирует транзакцию на TON_WALLET_ADDRESS с этим
   комментарием в payload — сам перевод инициирует кошелёк пользователя,
   бэкенду для этого шага ничего вызывать не нужно.
2. check_payment_status опрашивает TON Center v3 (/transactions?account=...),
   ищет входящую транзакцию с text_comment == external_id и суммой не меньше
   ожидаемой, подтверждённую мастерчейном (mc_block_seqno не None — раньше
   этого транзакция может быть ещё в шардчейне и не финализирована).

Схема ответа TON Center проверена вживую (см. диалог: curl против реального
адреса TON_WALLET_ADDRESS, найдена настоящая входящая транзакция с
in_msg.message_content.decoded == {'@type': 'text_comment', 'comment': ...}).

Никогда не возвращаем 'failed' — в отличие от Platega, где провайдер
сам сообщает о просрочке/отмене, здесь "неудачи" не существует как события:
либо перевод рано или поздно найдётся в блокчейне, либо пользователь просто
не заплатил. Зависшие TON-платежи закрывает тот же ABANDONED_PAYMENT_DELAY-
поллинг напоминаний (background.py), что и для остальных провайдеров.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.services.payment.base import CreatedPayment, PaymentProvider

logger = logging.getLogger(__name__)

TONCENTER_BASE_URL = 'https://toncenter.com/api/v3'
_TRANSACTIONS_LIMIT = 50
_NANOTONS_PER_TON = 1_000_000_000


def _kopeks_to_nanotons(amount_kopeks: int) -> int:
    return (amount_kopeks * _NANOTONS_PER_TON) // settings.TON_RATE_KOPEKS


class TonProvider(PaymentProvider):
    provider_name = 'ton'

    async def create_payment(
        self, *, user_id: int, amount_kopeks: int, description: str, bot=None, telegram_id=None
    ) -> CreatedPayment:
        # Комментарий — единственный способ сматчить конкретный перевод с
        # конкретным Payment (TON не поддерживает произвольные метаданные
        # платежа, только текстовый комментарий в самом сообщении перевода).
        # Короткий и без пробелов/спецсимволов — фронтенд/deep-link кладёт его
        # в payload transaction'а как есть.
        external_id = f'nrw{uuid.uuid4().hex[:12]}'

        # ton://transfer — универсальная deep-link-схема (открывает любой
        # установленный TON-кошелёк с уже заполненными адресом/суммой/
        # комментарием), тот же принцип, что и payment_url у Platega
        # ("Перейти к оплате" в handlers/subscription.py — см. kb с url-кнопкой).
        # Полноценный TON Connect (выбор конкретного кошелька, QR для десктопа)
        # даём на странице оплаты NRW-MiniApp через @tonconnect/ui-react — там
        # есть браузер для этого, в самом чате бота показывать компонент неоткуда.
        nanotons = _kopeks_to_nanotons(amount_kopeks)
        payment_url = (
            f'ton://transfer/{settings.TON_WALLET_ADDRESS}'
            f'?amount={nanotons}&text={quote(external_id)}'
        )
        return CreatedPayment(external_id=external_id, payment_url=payment_url, status='pending')

    async def verify_webhook(self, payload: dict, headers: dict) -> bool:
        # У TON в принципе нет вебхуков — см. докстринг модуля, только поллинг.
        raise NotImplementedError('У TON нет вебхука — подтверждение через check_payment_status (поллинг)')

    async def check_payment_status(self, external_id: str, *, amount_kopeks: int | None = None) -> str:
        if not settings.TON_WALLET_ADDRESS:
            logger.warning('TonProvider.check_payment_status вызван без настроенного TON_WALLET_ADDRESS')
            return 'pending'

        params: dict[str, Any] = {
            'account': settings.TON_WALLET_ADDRESS,
            'limit': _TRANSACTIONS_LIMIT,
        }
        headers = {}
        if settings.TONCENTER_API_KEY:
            headers['X-API-Key'] = settings.TONCENTER_API_KEY

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f'{TONCENTER_BASE_URL}/transactions', params=params, headers=headers)
        except httpx.HTTPError as error:
            logger.warning('TON Center запрос не удался: %s', error)
            return 'pending'

        if response.status_code == 429:
            logger.warning('TON Center: рейт-лимит (429) — попробуем на следующей итерации поллинга')
            return 'pending'
        if response.status_code >= 400:
            logger.warning('TON Center вернул %s: %s', response.status_code, response.text[:200])
            return 'pending'

        try:
            data = response.json()
        except ValueError:
            logger.warning('TON Center вернул не-JSON ответ')
            return 'pending'

        expected_nanotons = _kopeks_to_nanotons(amount_kopeks) if amount_kopeks is not None else 0

        for tx in data.get('transactions') or []:
            in_msg = tx.get('in_msg') or {}
            decoded = ((in_msg.get('message_content') or {}).get('decoded')) or {}
            if decoded.get('@type') != 'text_comment':
                continue
            if decoded.get('comment') != external_id:
                continue

            # Не финализирована мастерчейном — ещё может быть отменена
            # (реорганизация шардчейна), рано засчитывать.
            if tx.get('mc_block_seqno') is None:
                continue

            try:
                value_nanotons = int(in_msg.get('value') or 0)
            except (TypeError, ValueError):
                value_nanotons = 0

            if value_nanotons < expected_nanotons:
                logger.warning(
                    'TON платёж external_id=%s: получено %s нанотон, ожидалось не менее %s — недоплата',
                    external_id, value_nanotons, expected_nanotons,
                )
                continue

            return 'success'

        return 'pending'
