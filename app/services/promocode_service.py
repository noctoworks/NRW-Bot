"""Владелец: агент referral-promo. Используется handlers/promocode.py. См. §9.7
clone-architecture.md. Формат кода — читаемый (SUMMER2026), не случайный токен —
это UX-требование к тому, что вводит пользователь; сам код генерирует админ
вручную при создании (handlers/admin.py), а не promocode_service.

TODO(agent:referral-promo): реализовать тело функции.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PromoCode, PromoCodeUse, Tariff, User
from app.services.subscription_provisioning import provision_or_extend_subscription


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
    normalized = code.strip().upper()
    # with_for_update() блокирует строку промокода до конца транзакции (реально
    # работает на Postgres в проде; SQLite это условие молча игнорирует) — без
    # этого два одновременных активатора могут оба пройти проверку
    # activations_count >= max_activations до того, как первый закоммитит,
    # и превысить заявленный лимит активаций.
    result = await db.execute(
        select(PromoCode).where(func.upper(PromoCode.code) == normalized).with_for_update()
    )
    promocode = result.scalar_one_or_none()

    if promocode is None:
        raise PromoCodeError('Промокод не найден')
    if not promocode.is_active:
        raise PromoCodeError('Промокод больше не активен')
    if promocode.expires_at is not None:
        expires_at = promocode.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise PromoCodeError('Срок действия промокода истёк')
    use_result = await db.execute(
        select(PromoCodeUse).where(
            PromoCodeUse.promocode_id == promocode.id, PromoCodeUse.user_id == user.id
        )
    )
    if use_result.scalar_one_or_none() is not None:
        raise PromoCodeError('Вы уже использовали этот промокод')

    if promocode.activations_count >= promocode.max_activations:
        raise PromoCodeError('Лимит активаций промокода исчерпан')

    if promocode.type == 'balance':
        user.balance_kopeks += promocode.value
    elif promocode.type == 'days':
        tariff_result = await db.execute(
            select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id).limit(1)
        )
        tariff = tariff_result.scalar_one_or_none()
        if tariff is None:
            raise PromoCodeError('Нет доступного тарифа для начисления дней подписки')
        await provision_or_extend_subscription(db, user=user, tariff=tariff, period_days=promocode.value)
    else:
        raise PromoCodeError(f'Неизвестный тип промокода: {promocode.type}')

    promocode.activations_count += 1
    db.add(PromoCodeUse(promocode_id=promocode.id, user_id=user.id))
    await db.flush()

    return PromoCodeResult(type=promocode.type, value=promocode.value)
