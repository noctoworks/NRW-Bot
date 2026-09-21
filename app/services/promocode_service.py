"""Владелец: агент referral-promo. Используется handlers/promocode.py. См. §9.7
clone-architecture.md. Формат кода — читаемый (SUMMER2026), не случайный токен —
это UX-требование к тому, что вводит пользователь; сам код генерирует админ
вручную при создании (handlers/admin.py), а не promocode_service.

TODO(agent:referral-promo): реализовать тело функции.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PromoCode, PromoCodeUse, Tariff, User
from app.logging_setup import get_logger
from app.services.balance_service import credit_balance
from app.services.subscription_provisioning import provision_or_extend_subscription


log = get_logger(__name__)


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
    # Проверки ниже — только ради понятных сообщений; настоящую защиту от гонки
    # даёт атомарный "захват" слота (UPDATE ... WHERE activations_count <
    # max_activations) чуть дальше. Он работает одинаково на Postgres и SQLite,
    # в отличие от SELECT ... FOR UPDATE, который SQLite молча игнорирует.
    #
    # ВАЖНО: обработчики бота ловят PromoCodeError и возвращаются как обычно, а
    # AuthMiddleware после этого коммитит сессию — поэтому PromoCodeError бросаем
    # только ДО каких-либо изменений (либо после rollback).
    result = await db.execute(select(PromoCode).where(func.upper(PromoCode.code) == normalized))
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

    tariff = None
    if promocode.type == 'days':
        tariff_result = await db.execute(
            select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id).limit(1)
        )
        tariff = tariff_result.scalar_one_or_none()
        if tariff is None:
            raise PromoCodeError('Нет доступного тарифа для начисления дней подписки')
    elif promocode.type != 'balance':
        raise PromoCodeError(f'Неизвестный тип промокода: {promocode.type}')

    # Атомарный захват слота: два одновременных активатора последней активации не
    # пройдут оба — второй UPDATE не затронет ни одной строки. Ничего не изменено
    # (rowcount == 0), поэтому просто бросаем ошибку.
    claim = await db.execute(
        update(PromoCode)
        .where(
            PromoCode.id == promocode.id,
            PromoCode.is_active.is_(True),
            PromoCode.activations_count < PromoCode.max_activations,
        )
        .values(activations_count=PromoCode.activations_count + 1)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount == 0:
        await db.refresh(promocode)
        if not promocode.is_active:
            raise PromoCodeError('Промокод больше не активен')
        raise PromoCodeError('Лимит активаций промокода исчерпан')

    # Тот же пользователь дважды параллельно: оба прошли проверку выше, второй
    # упрётся в uq_promocode_user. Откатываем транзакцию целиком (вместе с
    # захваченным слотом), иначе AuthMiddleware закоммитил бы лишнюю активацию.
    db.add(PromoCodeUse(promocode_id=promocode.id, user_id=user.id))
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise PromoCodeError('Вы уже использовали этот промокод') from None

    if promocode.type == 'balance':
        await credit_balance(db, user, promocode.value, reason='promocode')
    else:
        await provision_or_extend_subscription(db, user=user, tariff=tariff, period_days=promocode.value)

    await db.refresh(promocode, ['activations_count'])
    log.info(
        'promocode_activated',
        user_id=user.id,
        code=promocode.code,
        type=promocode.type,
        value=promocode.value,
        activations=f'{promocode.activations_count}/{promocode.max_activations}',
    )
    return PromoCodeResult(type=promocode.type, value=promocode.value)
