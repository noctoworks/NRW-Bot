"""Балансировка платежей между Platega и cisPay (см. диалог: "cisPay как основной
платежкой, взамену Platega ... каждый второй платёж будет идти через cisPay").

Пользователь по-прежнему видит ОДНУ кнопку способа оплаты — публичный ключ
'platega' в PAYMENT_METHOD_LABELS (app/handlers/subscription.py), подпись
"Карты и СБП" не менялась. Под капотом create_split_payment случайно выбирает
реального провайдера 50/50 — БЕЗ персистентного счётчика (см. диалог: точное
чередование 1-2-1-2 потребовало бы отдельной строки в БД с SELECT...FOR UPDATE,
как у списания баланса, — сознательно не стали ради простоты, random даёт
статистически равный сплит на объёме). Реальное имя выбранного провайдера
('platega' или 'cispay') ОБЯЗАН сохранить вызывающий код в Payment.provider —
не публичный ключ метода, а фактический — иначе вебхуки (/platega-webhook,
/cispay-webhook в app/cabinet/webhooks.py) и payment_poll_loop
(app/services/background.py, дергает get_payment_provider(payment.provider))
не найдут правильного провайдера для проверки статуса этого платежа.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from app.services.payment import get_payment_provider
from app.services.payment.base import CreatedPayment

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

# Публичный ключ метода 'platega' (см. PAYMENT_METHOD_LABELS) теперь означает
# "СБП/карты, провайдер выбирается автоматически", а не буквально Platega.
# Вывести провайдера из ротации (инцидент/временное отключение) — убрать его
# отсюда, без изменений в вызывающем коде (create_split_payment с одним
# элементом просто всегда выбирает его же).
SPLIT_PROVIDERS: tuple[str, ...] = ('platega', 'cispay')


async def create_split_payment(
    *, user_id: int, amount_kopeks: int, description: str, bot: 'Bot | None' = None, telegram_id: int | None = None
) -> tuple[str, CreatedPayment]:
    """(реальное_имя_провайдера, CreatedPayment). Пробует случайно выбранного
    провайдера первым; при ЛЮБОЙ ошибке create_payment (сеть/5xx/невалидный
    ответ — всё, что PlategaProvider/CisPayProvider заворачивают в RuntimeError)
    — автоматически пробует второго, а не отдаёт ошибку сразу пользователю
    (см. диалог: сбой одного провайдера не должен блокировать оплату, пока жив
    хотя бы один). Если и второй падает — исключение пробрасывается наружу
    как раньше (оба провайдера недоступны, дальше решать вызывающему коду)."""
    primary = random.choice(SPLIT_PROVIDERS)
    secondary = SPLIT_PROVIDERS[1] if primary == SPLIT_PROVIDERS[0] else SPLIT_PROVIDERS[0]

    try:
        provider = get_payment_provider(primary)
        created = await provider.create_payment(
            user_id=user_id, amount_kopeks=amount_kopeks, description=description, bot=bot, telegram_id=telegram_id
        )
        return primary, created
    except Exception:
        logger.warning('create_split_payment: %s недоступен, пробуем %s', primary, secondary, exc_info=True)

    provider = get_payment_provider(secondary)
    created = await provider.create_payment(
        user_id=user_id, amount_kopeks=amount_kopeks, description=description, bot=bot, telegram_id=telegram_id
    )
    return secondary, created
