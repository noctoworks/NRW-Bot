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
# элементом всегда выбирает его же, без фоллбека — см. ниже).
#
# cisPay временно выключен из ротации 2026-09-12 — их сторона не смогла
# провести ни один реальный SBP-платёж (available_methods: [] даже у свежесозданной
# тестовой транзакции, см. диалог), хотя /store/capabilities показывает SBP как
# is_active. Ждём подтверждения от саппорта cisPay, что эквайринг реально
# подключен, потом вернуть 'cispay' в кортеж обратно.
SPLIT_PROVIDERS: tuple[str, ...] = ('platega',)


async def create_split_payment(
    *, user_id: int, amount_kopeks: int, description: str, bot: 'Bot | None' = None, telegram_id: int | None = None
) -> tuple[str, CreatedPayment]:
    """(реальное_имя_провайдера, CreatedPayment). Пробует случайно выбранного
    провайдера первым; при ЛЮБОЙ ошибке create_payment (сеть/5xx/невалидный
    ответ — всё, что PlategaProvider/CisPayProvider заворачивают в RuntimeError)
    — автоматически пробует следующего по списку, а не отдаёт ошибку сразу
    пользователю (см. диалог: сбой одного провайдера не должен блокировать
    оплату, пока жив хотя бы один). Если SPLIT_PROVIDERS содержит один элемент
    (провайдер временно выведен из ротации) — фоллбека нет, ошибка пробрасывается
    как есть. Если упали ВСЕ — тоже пробрасывается наружу (дальше решать
    вызывающему коду)."""
    providers = list(SPLIT_PROVIDERS)
    random.shuffle(providers)

    last_error: Exception | None = None
    for index, name in enumerate(providers):
        try:
            provider = get_payment_provider(name)
            created = await provider.create_payment(
                user_id=user_id, amount_kopeks=amount_kopeks, description=description, bot=bot, telegram_id=telegram_id
            )
            return name, created
        except Exception as error:
            last_error = error
            remaining = providers[index + 1 :]
            if remaining:
                logger.warning('create_split_payment: %s недоступен, пробуем %s', name, remaining[0], exc_info=True)

    assert last_error is not None  # providers всегда непустой (SPLIT_PROVIDERS)
    raise last_error
