"""Общий хелпер для "выдать/продлить подписку на N дней" — переиспользуется
gift_service.redeem_gift_code (§9.4) и promocode_service.activate_promocode
(§9.7, type=days). Обе ветки идентичны обычной покупке подписки (§9.2): если
у пользователя ещё нет Subscription — create_user в Remnawave + INSERT
Subscription, если уже есть — extend_user_expiration + продление end_date.

Не владелец этого файла — handlers/subscription.py (агент subscription) может
взять на вооружение тот же паттерн при реализации покупки/продления, но это
не обязательство: контракт зафиксирован только для gift_service/promocode_service.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Subscription, Tariff, User
from app.external.remnawave import get_remnawave_client

logger = logging.getLogger(__name__)


async def provision_or_extend_subscription(
    db: AsyncSession, *, user: User, tariff: Tariff, period_days: int
) -> Subscription:
    """Создаёт новую подписку (первая активация) либо продлевает существующую.

    Обновляет remnawave-состояние синхронно (create_user/extend_user_expiration) —
    если это упадёт, исключение пробрасывается наружу (в отличие от referral_service,
    здесь ошибка Remnawave критична для флоу и должна откатить транзакцию/показать
    пользователю ошибку).
    """
    now = datetime.now(timezone.utc)
    client = get_remnawave_client()

    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    subscription = result.scalar_one_or_none()

    if subscription is not None:
        base = subscription.end_date
        if base is not None and base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        if base is None or base < now:
            base = now
        new_end = base + timedelta(days=period_days)

        if user.remnawave_uuid:
            await client.extend_user_expiration(remnawave_uuid=user.remnawave_uuid, expire_at=new_end)
            # Если подписка была истёкшей, Remnawave-пользователь мог быть отключён
            # фоновой задачей expiry_checker (см. app/services/background.py) — без
            # явного enable_user продление здесь оживило бы запись в БД, но не сам
            # VPN-доступ на панели. Баг найден при сведении параллельных модулей
            # (subscription.py уже делал enable_user, этот файл — нет).
            await client.enable_user(remnawave_uuid=user.remnawave_uuid)

        subscription.end_date = new_end
        subscription.status = 'active'
        subscription.tariff_id = tariff.id
        # Сброс флагов напоминаний — иначе после продления expiry_checker (§12а)
        # не пришлёт напоминание для НОВОЙ даты окончания, т.к. флаг уже стоит True
        # с предыдущего цикла подписки (то же самое делает subscription.py).
        subscription.reminder_3d_sent = False
        subscription.reminder_1d_sent = False
        await db.flush()
        return subscription

    new_end = now + timedelta(days=period_days)
    rw_user = await client.create_user(
        telegram_id=user.telegram_id,
        squad_uuids=tariff.squad_uuids,
        traffic_limit_gb=tariff.traffic_limit_gb,
        expire_at=new_end,
    )
    user.remnawave_uuid = rw_user.uuid

    subscription = Subscription(
        user_id=user.id,
        tariff_id=tariff.id,
        status='active',
        end_date=new_end,
        traffic_limit_gb=tariff.traffic_limit_gb,
        device_limit=tariff.device_limit,
        subscription_url=rw_user.subscription_url,
        short_uuid=rw_user.short_uuid,
    )
    db.add(subscription)
    await db.flush()
    return subscription
