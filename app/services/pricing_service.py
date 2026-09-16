"""Единая точка расчёта цены подписки — переиспользуется и ботом
(handlers/subscription.py, handlers/gift.py), и Mini App (cabinet/routes.py),
чтобы скидка промогруппы (см. PromoGroup) применялась ОДИНАКОВО везде, а не
дублировалась в нескольких местах с риском разъехаться.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BotSetting, PromoGroup, Subscription, Tariff, User

# Ключи в bot_settings под сайтовую акцию (см. диалог 2026-09-16: "скидка 20%
# на все тарифы до 18 числа") — в отличие от PromoGroup (постоянная скидка на
# КОНКРЕТНОГО юзера), это временная скидка на ВСЕХ сразу, с датой окончания.
# bot_settings была заведена в модели, но нигде не использовалась — первый
# реальный потребитель. Значения — простые строки (не JSON), не хранится
# ничего чувствительного, отдельная таблица под "одну акцию за раз" излишня.
SALE_DISCOUNT_PERCENT_KEY = 'sale_discount_percent'
SALE_ENDS_AT_KEY = 'sale_ends_at'

# Win-back-скидка на первую покупку тем, у кого только что закончился бесплатный
# триал (см. диалог 2026-09-13, идея из разбора воронки конверсии MiniApp) —
# 20% в течение 48 часов после истечения триала. is_trial остаётся True, пока
# не пройдёт НАСТОЯЩАЯ оплата (см. subscription_provisioning.py) — значит
# is_trial=True + status='expired' однозначно значит "ни разу не платил".
TRIAL_WINBACK_DISCOUNT_PERCENT = 20
TRIAL_WINBACK_WINDOW = timedelta(hours=48)


async def get_trial_winback_discount(db: AsyncSession, user: User) -> tuple[int, datetime | None]:
    """(процент, дедлайн) win-back скидки — (0, None), если не применима."""
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    subscription = result.scalar_one_or_none()
    if subscription is None or not subscription.is_trial or subscription.status != 'expired':
        return 0, None

    end = subscription.end_date
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    deadline = end + TRIAL_WINBACK_WINDOW
    if datetime.now(timezone.utc) > deadline:
        return 0, None
    return TRIAL_WINBACK_DISCOUNT_PERCENT, deadline


async def get_active_sale_discount(db: AsyncSession) -> tuple[int, datetime | None]:
    """(процент, дедлайн) сайтовой акции на ВСЕ тарифы сразу (см. диалог
    2026-09-16) — настраивается двумя строками в bot_settings, не требует
    привязки к промогруппе/юзеру. (0, None), если акции нет, дата не
    распарсилась, или дедлайн уже прошёл — тихий фоллбек на "акции нет", а не
    ошибка (акцию иногда забывают выключить руками после дедлайна, это не
    должно ронять расчёт цены)."""
    percent_row = await db.get(BotSetting, SALE_DISCOUNT_PERCENT_KEY)
    ends_row = await db.get(BotSetting, SALE_ENDS_AT_KEY)
    if percent_row is None or ends_row is None:
        return 0, None
    try:
        percent = int(percent_row.value)
        ends_at = datetime.fromisoformat(ends_row.value)
    except ValueError:
        return 0, None
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    if percent <= 0 or datetime.now(timezone.utc) > ends_at:
        return 0, None
    return percent, ends_at


async def get_best_discount(db: AsyncSession, user: User) -> tuple[int, datetime | None]:
    """(процент, дедлайн) максимальной из скидки промогруппы (без дедлайна),
    win-back после триала и сайтовой акции (см. get_active_sale_discount) —
    НЕ суммируются, берём только самую выгодную (у кого личная скидка выше
    акции — акция её не срежет). Явный запрос PromoGroup по
    user.promo_group_id вместо lazy-доступа к user.promo_group —
    AuthMiddleware грузит User без selectinload(promo_group), ленивый доступ
    к relationship упал бы MissingGreenlet (тот же класс проблемы, что
    известный баг с User.subscription, см. handlers/admin.py)."""
    group_discount = 0
    if user.promo_group_id is not None:
        group = await db.get(PromoGroup, user.promo_group_id)
        group_discount = group.discount_percent if group else 0
    trial_discount, trial_deadline = await get_trial_winback_discount(db, user)
    sale_discount, sale_deadline = await get_active_sale_discount(db)

    candidates: list[tuple[int, datetime | None]] = [
        (group_discount, None),
        (trial_discount, trial_deadline),
        (sale_discount, sale_deadline),
    ]
    return max(candidates, key=lambda c: c[0])


async def get_discount_percent(db: AsyncSession, user: User) -> int:
    """Только процент — для мест, которым дедлайн не нужен (расчёт цены
    покупки/смены тарифа). См. get_best_discount для деталей выбора."""
    percent, _ = await get_best_discount(db, user)
    return percent


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


async def get_daily_price_kopeks(db: AsyncSession, tariff: Tariff, user: User) -> float:
    """Условная "цена дня" тарифа — 30-дневная цена / 30, со скидкой юзера.
    Используется только для пропорционального перерасчёта при смене тарифа на
    активной подписке (см. app/services/tariff_change_service.py) — все тарифы
    обязаны иметь цену за 30 дней (см. scripts/seed.py)."""
    monthly = await get_period_price_kopeks(db, tariff, 30, user)
    return monthly / 30
