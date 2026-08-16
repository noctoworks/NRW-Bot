"""Контракт между start.py (вызывает redeem_gift_code при /start gift_CODE) и
gift.py (владеет реализацией, включая создание кода при покупке подарка).
См. §9.4 clone-architecture.md.

TODO(agent:referral-promo): реализовать тело функций.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import GiftCode, Subscription, Tariff, User
from app.services.subscription_provisioning import provision_or_extend_subscription

logger = logging.getLogger(__name__)

# Разумный дефолт срока жизни неактивированного подарочного кода (не в архитектурном
# документе явно — решение агента: если код никто не активировал за месяц, он протухает).
GIFT_CODE_TTL_DAYS = 30


class GiftCodeError(Exception):
    """Код не найден / уже использован / истёк — текст в str(exc), для показа пользователю."""


def generate_gift_code(length: int = 10) -> str:
    import secrets
    import string

    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


async def create_gift_code(db: AsyncSession, *, tariff: Tariff, period_days: int, gifter: User) -> GiftCode:
    """Списание средств у gifter должно произойти ДО вызова этой функции (в handlers/gift.py),
    здесь только создание записи GiftCode."""
    code = generate_gift_code()
    for _ in range(10):
        result = await db.execute(select(GiftCode.id).where(GiftCode.code == code))
        if result.scalar_one_or_none() is None:
            break
        code = generate_gift_code()
    else:
        raise RuntimeError('Не удалось сгенерировать уникальный gift-код за 10 попыток')

    gift_code = GiftCode(
        code=code,
        tariff_id=tariff.id,
        period_days=period_days,
        gifter_user_id=gifter.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=GIFT_CODE_TTL_DAYS),
    )
    db.add(gift_code)
    await db.flush()
    return gift_code


async def redeem_gift_code(
    db: AsyncSession, *, code: str, recipient: User, bot: Bot | None = None
) -> Subscription:
    """Активирует подписку у recipient (create_user/extend_user_expiration через
    get_remnawave_client()), помечает GiftCode как использованный. Бросает GiftCodeError
    при невалидном/использованном/истёкшем коде — start.py должен поймать и показать пользователю.

    `bot` — необязательный параметр (сохраняет обратную совместимость со старыми вызовами):
    если передан, в конце (вне критичного пути) шлёт notify_gift_redeemed_to_gifter дарителю.
    Если None (например, будущий вызов из /cabinet API, у которого нет aiogram Bot) —
    уведомление просто не отправляется.
    """
    normalized = code.strip().upper()
    result = await db.execute(select(GiftCode).where(func.upper(GiftCode.code) == normalized))
    gift_code = result.scalar_one_or_none()

    if gift_code is None:
        raise GiftCodeError('Код не найден')
    if gift_code.redeemed_at is not None:
        raise GiftCodeError('Код уже использован')
    if gift_code.expires_at is not None:
        expires_at = gift_code.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise GiftCodeError('Срок действия кода истёк')

    tariff_result = await db.execute(select(Tariff).where(Tariff.id == gift_code.tariff_id))
    tariff = tariff_result.scalar_one_or_none()
    if tariff is None:
        raise GiftCodeError('Тариф подарка недоступен')

    subscription = await provision_or_extend_subscription(
        db, user=recipient, tariff=tariff, period_days=gift_code.period_days
    )

    gift_code.redeemed_by_user_id = recipient.id
    gift_code.redeemed_at = datetime.now(timezone.utc)
    await db.flush()

    if bot is not None:
        try:
            gifter_result = await db.execute(select(User).where(User.id == gift_code.gifter_user_id))
            gifter = gifter_result.scalar_one_or_none()
            if gifter is not None:
                from app.services.notification_service import notify_gift_redeemed_to_gifter

                await notify_gift_redeemed_to_gifter(
                    bot, gifter_telegram_id=gifter.telegram_id, recipient_username=recipient.username
                )
        except Exception:
            logger.exception('notify_gift_redeemed_to_gifter failed for gift_code_id=%s', gift_code.id)

    return subscription
