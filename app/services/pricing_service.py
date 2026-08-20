"""Единая точка расчёта цены подписки — переиспользуется и ботом
(handlers/subscription.py, handlers/gift.py), и Mini App (cabinet/routes.py),
чтобы скидка промогруппы (см. PromoGroup) применялась ОДИНАКОВО везде, а не
дублировалась в нескольких местах с риском разъехаться.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PromoGroup, Tariff, User


async def get_discount_percent(db: AsyncSession, user: User) -> int:
    """Явный запрос PromoGroup по user.promo_group_id вместо lazy-доступа к
    user.promo_group — AuthMiddleware грузит User без selectinload(promo_group),
    ленивый доступ к relationship упал бы MissingGreenlet (тот же класс проблемы,
    что известный баг с User.subscription, см. handlers/admin.py)."""
    if user.promo_group_id is None:
        return 0
    group = await db.get(PromoGroup, user.promo_group_id)
    return group.discount_percent if group else 0


def apply_discount(price_kopeks: int, discount_percent: int) -> int:
    """Округляем ДО ЦЕЛОГО РУБЛЯ, всегда вниз — в пользу пользователя (см.
    диалог: на боевой базе уже есть копейки от старой формулы, дробные суммы
    к оплате/на балансе не должны появляться впредь; округление в пользу
    юзера снимает вопрос "почему с меня взяли лишнее")."""
    if discount_percent <= 0:
        return price_kopeks
    # price_kopeks * (100 - discount_percent) / 10000 == price_kopeks * (100 - discount_percent) / 100 / 100,
    # т.е. цена в рублях как точная дробь; //10000 floor'ит её до целого рубля.
    return (price_kopeks * (100 - discount_percent) // 10000) * 100


async def get_period_price_kopeks(db: AsyncSession, tariff: Tariff, period_days: int, user: User) -> int:
    """Базовая цена тарифа за период минус скидка промогруппы юзера (если есть)."""
    base = int(tariff.period_prices_kopeks[str(period_days)])
    discount_percent = await get_discount_percent(db, user)
    return apply_discount(base, discount_percent)
