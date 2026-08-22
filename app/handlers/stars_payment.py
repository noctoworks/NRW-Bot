"""Telegram Stars — подтверждение оплаты. Создание счёта — в
app/services/payment/stars.py (Bot.send_invoice), сюда прилетает только реакция
Telegram на этот счёт.

pre_checkout_query — Telegram требует ответ в течение 10 секунд после того, как
пользователь нажал "Заплатить" в счёте, иначе платёж отменяется автоматически
на стороне Telegram, до какого-либо списания звёзд.

successful_payment — приходит уже ПОСЛЕ реального списания звёзд у пользователя;
единственный момент, когда Stars-платёж вообще можно подтвердить — в отличие от
Platega/TON, у Stars нет API для опроса статуса конкретного счёта (см.
StarsProvider.check_payment_status), поэтому payment_poll_loop для Stars бесполезен.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Payment
from app.services.payment_finalization import finalize_pending_payment

logger = logging.getLogger(__name__)

router = Router(name='stars_payment')


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, db: AsyncSession, bot: Bot) -> None:
    payload = message.successful_payment.invoice_payload
    result = await db.execute(
        select(Payment).where(
            Payment.provider == 'stars', Payment.external_id == payload, Payment.status == 'pending'
        )
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        # Не должно происходить в норме (Telegram не подтвердит оплату счёта,
        # которого мы не создавали) — но если случилось, важно не потерять
        # молча: юзер реально заплатил звёздами, а подписка/подарок не выданы.
        logger.error(
            'successful_payment: не найден pending Payment(provider=stars) для payload=%s, юзер=%s — реальные звёзды списаны без выдачи',
            payload,
            message.from_user.id if message.from_user else None,
        )
        return

    await finalize_pending_payment(db, payment, bot)


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
