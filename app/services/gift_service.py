"""Контракт между start.py (вызывает redeem_gift_code при /start gift_CODE) и
gift.py (владеет реализацией, включая создание кода при покупке подарка).
См. §9.4 clone-architecture.md.

TODO(agent:referral-promo): реализовать тело функций.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import GiftCode, Subscription, Tariff, User


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
    raise NotImplementedError


async def redeem_gift_code(db: AsyncSession, *, code: str, recipient: User) -> Subscription:
    """Активирует подписку у recipient (create_user/extend_user_expiration через
    get_remnawave_client()), помечает GiftCode как использованный. Бросает GiftCodeError
    при невалидном/использованном/истёкшем коде — start.py должен поймать и показать пользователю."""
    raise NotImplementedError
