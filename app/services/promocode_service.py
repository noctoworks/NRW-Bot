"""Владелец: агент referral-promo. Используется handlers/promocode.py. См. §9.7
clone-architecture.md. Формат кода — читаемый (SUMMER2026), не случайный токен —
это UX-требование к тому, что вводит пользователь; сам код генерирует админ
вручную при создании (handlers/admin.py), а не promocode_service.

TODO(agent:referral-promo): реализовать тело функции.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User


class PromoCodeError(Exception):
    """Не найден / неактивен / истёк / лимит активаций / уже использован этим пользователем."""


@dataclass
class PromoCodeResult:
    type: str  # balance|days
    value: int


async def activate_promocode(db: AsyncSession, *, code: str, user: User) -> PromoCodeResult:
    """type=balance -> начислить value копеек на User.balance_kopeks.
    type=days -> продлить Subscription на value дней (через get_remnawave_client().extend_user_expiration,
    если подписки ещё нет — создать через create_user, как при обычной покупке).
    Бросает PromoCodeError с человекочитаемым текстом при любой невалидности."""
    raise NotImplementedError
