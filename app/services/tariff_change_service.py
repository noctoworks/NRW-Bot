"""Смена тарифа на уже активной подписке — пропорциональный перерасчёт (см.
диалог 2026-09-13, добавление тарифов "Онлайн"/"Семейный" в Mini App).

Модель расчёта: доплата = (дневная цена нового тарифа - дневная цена старого)
* оставшиеся дни подписки. Дата окончания (end_date) НЕ меняется — это не
продление, а замена тарифа на остаток уже оплаченного периода. Если новый
тариф дешевле (даунгрейд), доплата — 0, остаток не возвращается на баланс
(симметрично округлению в пользу юзера в pricing_service.apply_discount).

Оплата — только с баланса (instant): провайдерские платежи (Platega/TON/Stars)
асинхронны и требуют отдельной ветки в payment_finalization.py на подтверждение
именно смены тарифа, а не покупки/продления — осознанно не делаем в этой
итерации, при нехватке средств пользователь сначала пополняет баланс.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Subscription, Tariff, Transaction, User
from app.external.remnawave import get_remnawave_client
from app.handlers.subscription import InsufficientBalanceError
from app.services.pricing_service import get_daily_price_kopeks


def remaining_days(subscription: Subscription, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    end = subscription.end_date
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, (end - now).days)


async def compute_change_price_kopeks(
    db: AsyncSession, *, subscription: Subscription, current_tariff: Tariff, new_tariff: Tariff, user: User
) -> int:
    days = remaining_days(subscription)
    if days == 0:
        return 0
    old_daily = await get_daily_price_kopeks(db, current_tariff, user)
    new_daily = await get_daily_price_kopeks(db, new_tariff, user)
    return max(0, round((new_daily - old_daily) * days))


async def apply_tariff_change(
    db: AsyncSession, *, user: User, subscription: Subscription, new_tariff: Tariff, price_kopeks: int
) -> None:
    """Списывает price_kopeks с баланса (если > 0) и переключает подписку на
    new_tariff, сохраняя end_date — вызывающий обязан сам await db.commit()."""
    if price_kopeks > 0:
        locked = await db.execute(select(User).where(User.id == user.id).with_for_update())
        db_user = locked.scalar_one()
        if db_user.balance_kopeks < price_kopeks:
            raise InsufficientBalanceError(price_kopeks - db_user.balance_kopeks)
        db_user.balance_kopeks -= price_kopeks
        db.add(
            Transaction(
                user_id=user.id,
                type='subscription_payment',
                amount_kopeks=price_kopeks,
                status='completed',
                description=f'Смена тарифа на «{new_tariff.name}»',
            )
        )

    if user.remnawave_uuid:
        end = subscription.end_date
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        # extend_user_expiration с ТЕМ ЖЕ expire_at — единственный способ
        # протолкнуть новые squad_uuids/traffic_limit_gb на панель без
        # продления срока (отдельного "update без даты" в RemnawaveClient нет).
        await get_remnawave_client().extend_user_expiration(
            remnawave_uuid=user.remnawave_uuid,
            expire_at=end,
            traffic_limit_gb=new_tariff.traffic_limit_gb,
            squad_uuids=new_tariff.squad_uuids,
        )

    subscription.tariff_id = new_tariff.id
    subscription.traffic_limit_gb = new_tariff.traffic_limit_gb
    subscription.device_limit = new_tariff.device_limit
    await db.flush()
