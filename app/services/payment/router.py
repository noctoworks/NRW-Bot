"""Выбор провайдера для разовых платежей (см. диалог 2026-09-15: "cisPay как
единственный провайдер для разовых платежей, Platega остаётся только для
автосписаний/recurring" — cisPay не умеет подписки, поэтому autopay в
app/handlers/subscription.py:637 по-прежнему захардкожен на Platega напрямую,
этого модуля не касается).

Пользователь по-прежнему видит ОДНУ кнопку способа оплаты — публичный ключ
'platega' в PAYMENT_METHOD_LABELS (app/handlers/subscription.py), подпись
"Карты и СБП" не менялась. Под капотом create_split_payment резолвит реального
провайдера через SPLIT_PROVIDERS — при желании можно снова сделать сплит между
несколькими провайдерами (см. историю: 50/50 между Platega/cisPay работал
2026-09-12..2026-09-15), сейчас там один элемент, фоллбека нет. Реальное имя
выбранного провайдера ('platega' или 'cispay') ОБЯЗАН сохранить вызывающий код
в Payment.provider — не публичный ключ метода, а фактический — иначе вебхуки
(/platega-webhook, /cispay-webhook в app/cabinet/webhooks.py) и
payment_poll_loop (app/services/background.py, дергает
get_payment_provider(payment.provider)) не найдут правильного провайдера для
проверки статуса этого платежа.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
# 2026-09-15: по решению владельца cisPay — единственный провайдер разовых
# платежей (Platega из ротации убран). Если cisPay снова начнёт сбоить
# (как 2026-09-12) — фоллбека НЕТ, ошибка идёт пользователю напрямую; вернуть
# Platega в ротацию тем же способом, каким его временно убирали 2026-09-12
# ('platega', 'cispay') — если нужен снова сплит, а не полная замена.
SPLIT_PROVIDERS: tuple[str, ...] = ('cispay',)


async def _last_split_provider(db: AsyncSession, user_id: int) -> str | None:
    """Провайдер последнего (по created_at) платежа этого юзера через сплит,
    любого статуса. Используется, чтобы при повторной попытке оплаты (юзер
    нажал «Оплатить» ещё раз — предыдущий платёж завис/не прошёл) не предлагать
    того же провайдера снова, а сразу попробовать другого (см. диалог
    2026-09-13)."""
    from app.database.models import Payment

    result = await db.execute(
        select(Payment.provider)
        .where(Payment.user_id == user_id, Payment.provider.in_(SPLIT_PROVIDERS))
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_split_payment(
    *,
    db: AsyncSession,
    user_id: int,
    amount_kopeks: int,
    description: str,
    bot: 'Bot | None' = None,
    telegram_id: int | None = None,
    username: str | None = None,
) -> tuple[str, CreatedPayment]:
    """(реальное_имя_провайдера, CreatedPayment). Первым пробует провайдера,
    ОТЛИЧНОГО от того, что юзер получил в прошлый раз (см. _last_split_provider) —
    случайно, если предыдущего платежа не было/он был через провайдера, которого
    сейчас нет в ротации; при ЛЮБОЙ ошибке create_payment (сеть/5xx/невалидный
    ответ — всё, что PlategaProvider/CisPayProvider заворачивают в RuntimeError)
    — автоматически пробует следующего по списку, а не отдаёт ошибку сразу
    пользователю (см. диалог: сбой одного провайдера не должен блокировать
    оплату, пока жив хотя бы один). Если SPLIT_PROVIDERS содержит один элемент
    (провайдер временно выведен из ротации) — фоллбека нет, ошибка пробрасывается
    как есть. Если упали ВСЕ — тоже пробрасывается наружу (дальше решать
    вызывающему коду)."""
    providers = list(SPLIT_PROVIDERS)
    random.shuffle(providers)

    if len(providers) > 1:
        last_provider = await _last_split_provider(db, user_id)
        if last_provider in providers:
            # Отодвигаем в конец очереди — испытываем сначала другого,
            # к прошлому провайдеру возвращаемся только если все остальные упали.
            providers.remove(last_provider)
            providers.append(last_provider)

    last_error: Exception | None = None
    for index, name in enumerate(providers):
        try:
            provider = get_payment_provider(name)
            created = await provider.create_payment(
                user_id=user_id,
                amount_kopeks=amount_kopeks,
                description=description,
                bot=bot,
                telegram_id=telegram_id,
                username=username,
            )
            return name, created
        except Exception as error:
            last_error = error
            remaining = providers[index + 1 :]
            if remaining:
                logger.warning('create_split_payment: %s недоступен, пробуем %s', name, remaining[0], exc_info=True)

    assert last_error is not None  # providers всегда непустой (SPLIT_PROVIDERS)
    raise last_error
