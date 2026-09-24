"""app/services/pricing_service.py — скидки, акции, округление.

Деньги: округление всегда в пользу пользователя и до целого рубля, из
конкурирующих скидок берётся ОДНА самая выгодная (не сумма)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.database.models import BotSetting, PromoGroup, Subscription, User
from app.services.pricing_service import (
    SALE_DISCOUNT_PERCENT_KEY,
    SALE_ENDS_AT_KEY,
    TRIAL_DISCOUNT_LEAD,
    TRIAL_WINBACK_DISCOUNT_PERCENT,
    TRIAL_WINBACK_WINDOW,
    apply_discount,
    get_active_sale_discount,
    get_best_discount,
    get_daily_price_kopeks,
    get_period_price_kopeks,
    get_trial_winback_discount,
    trial_discount_at,
)
from tests.helpers import make_tariff, make_user

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


# --- apply_discount ------------------------------------------------------------


@pytest.mark.parametrize(
    'price, percent, expected',
    [
        (10000, 0, 10000),
        (10000, -5, 10000),  # некорректная скидка не увеличивает цену
        (10000, 100, 0),
        (29900, 20, 23900),  # 239.2 ₽ -> 239 ₽ (вниз, в пользу пользователя)
        (9999, 10, 8900),  # 89.99 ₽ -> 89 ₽
        (10000, 33, 6700),
        (15050, 50, 7500),  # 75.25 ₽ -> 75 ₽
    ],
)
def test_apply_discount(price, percent, expected):
    assert apply_discount(price, percent) == expected


@pytest.mark.parametrize('percent', range(1, 100, 7))
def test_discounted_price_is_whole_rubles_and_never_above_original(percent):
    for price in (9900, 29900, 39900, 149900):
        discounted = apply_discount(price, percent)
        assert discounted % 100 == 0
        assert discounted <= price


# --- сайтовая акция ------------------------------------------------------------


async def _set_sale(db, percent: str | None, ends_at: str | None) -> None:
    if percent is not None:
        db.add(BotSetting(key=SALE_DISCOUNT_PERCENT_KEY, value=percent))
    if ends_at is not None:
        db.add(BotSetting(key=SALE_ENDS_AT_KEY, value=ends_at))
    await db.flush()


def _sale_case(session_factory, percent, ends_at):
    async def scenario():
        async with session_factory() as db:
            await _set_sale(db, percent, ends_at)
            return await get_active_sale_discount(db)

    return asyncio.run(scenario())


def test_active_sale_returns_percent_and_deadline(session_factory):
    ends = NOW() + timedelta(days=2)

    percent, deadline = _sale_case(session_factory, '20', ends.isoformat())

    assert percent == 20 and deadline == ends


def test_sale_deadline_without_timezone_is_treated_as_utc(session_factory):
    ends = (NOW() + timedelta(days=2)).replace(tzinfo=None)

    percent, deadline = _sale_case(session_factory, '20', ends.isoformat())

    assert percent == 20 and deadline.tzinfo is not None


@pytest.mark.parametrize(
    'percent, ends_at',
    [
        ('20', (NOW() - timedelta(minutes=1)).isoformat()),  # дедлайн прошёл
        ('0', (NOW() + timedelta(days=1)).isoformat()),
        ('-10', (NOW() + timedelta(days=1)).isoformat()),
        ('abc', (NOW() + timedelta(days=1)).isoformat()),  # мусор вместо процента
        ('20', 'не дата'),  # мусор вместо даты
        ('20', None),  # нет одной из строк
        (None, (NOW() + timedelta(days=1)).isoformat()),
        (None, None),
    ],
    ids=['expired', 'zero', 'negative', 'bad_percent', 'bad_date', 'no_date', 'no_percent', 'no_sale'],
)
def test_sale_is_ignored_silently_when_misconfigured(session_factory, percent, ends_at):
    """Забытая/сломанная акция не должна ронять расчёт цены — тихий фоллбек на "акции нет"."""
    assert _sale_case(session_factory, percent, ends_at) == (0, None)


# --- win-back после триала -----------------------------------------------------


async def _user_with_subscription(factory, *, status, is_trial, ended_ago: timedelta) -> int:
    user_id = await make_user(factory)
    tariff_id = await make_tariff(factory)
    async with factory() as db:
        db.add(Subscription(user_id=user_id, tariff_id=tariff_id, status=status, is_trial=is_trial, end_date=NOW() - ended_ago))
        await db.commit()
    return user_id


def _winback(session_factory, **kwargs):
    async def scenario():
        user_id = await _user_with_subscription(session_factory, **kwargs)
        async with session_factory() as db:
            return await get_trial_winback_discount(db, await db.get(User, user_id))

    return asyncio.run(scenario())


def test_discount_applies_within_window_after_trial_expired(session_factory):
    percent, deadline = _winback(session_factory, status='expired', is_trial=True, ended_ago=timedelta(hours=1))

    assert percent == TRIAL_WINBACK_DISCOUNT_PERCENT
    assert timedelta(days=2, hours=22) < deadline - NOW() < TRIAL_WINBACK_WINDOW


def test_discount_applies_during_the_last_days_of_a_running_trial(session_factory):
    percent, deadline = _winback(session_factory, status='active', is_trial=True, ended_ago=-timedelta(days=1))

    assert percent == TRIAL_WINBACK_DISCOUNT_PERCENT
    # дедлайн — конец триала + окно после него, а не конец триала
    assert timedelta(days=3, hours=23) < deadline - NOW() < timedelta(days=1) + TRIAL_WINBACK_WINDOW


@pytest.mark.parametrize(
    'kwargs',
    [
        dict(status='expired', is_trial=True, ended_ago=TRIAL_WINBACK_WINDOW + timedelta(hours=1)),  # окно закрылось
        dict(status='active', is_trial=True, ended_ago=-(TRIAL_DISCOUNT_LEAD + timedelta(hours=1))),  # окно ещё не открылось
        dict(status='active', is_trial=True, ended_ago=-timedelta(days=5)),  # триал только начался
        dict(status='expired', is_trial=False, ended_ago=timedelta(hours=1)),  # уже платил
        dict(status='active', is_trial=False, ended_ago=-timedelta(hours=5)),  # платный клиент в последние дни
        dict(status='disabled', is_trial=True, ended_ago=timedelta(hours=1)),  # отключён администратором
    ],
    ids=['window_closed', 'window_not_open_yet', 'trial_just_started', 'was_paying_customer', 'paying_customer_active', 'disabled'],
)
def test_discount_not_applicable(session_factory, kwargs):
    assert _winback(session_factory, **kwargs) == (0, None)


def test_discount_window_boundaries_are_inclusive_and_exact():
    end = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    trial = Subscription(is_trial=True, status='active', end_date=end)
    one_second = timedelta(seconds=1)

    assert trial_discount_at(trial, end - TRIAL_DISCOUNT_LEAD) == (TRIAL_WINBACK_DISCOUNT_PERCENT, end + TRIAL_WINBACK_WINDOW)
    assert trial_discount_at(trial, end - TRIAL_DISCOUNT_LEAD - one_second) == (0, None)
    assert trial_discount_at(trial, end + TRIAL_WINBACK_WINDOW) == (TRIAL_WINBACK_DISCOUNT_PERCENT, end + TRIAL_WINBACK_WINDOW)
    assert trial_discount_at(trial, end + TRIAL_WINBACK_WINDOW + one_second) == (0, None)


def test_discount_window_lengths_are_two_days_before_and_three_days_after():
    assert TRIAL_DISCOUNT_LEAD == timedelta(days=2)
    assert TRIAL_WINBACK_WINDOW == timedelta(days=3)


def test_discount_for_naive_datetimes_is_treated_as_utc():
    """На SQLite даты приходят без часового пояса — окно считается по UTC."""
    end = datetime(2026, 9, 24, 12, 0)  # naive
    trial = Subscription(is_trial=True, status='expired', end_date=end)

    assert trial_discount_at(trial, datetime(2026, 9, 25, tzinfo=timezone.utc))[0] == TRIAL_WINBACK_DISCOUNT_PERCENT


def test_winback_without_subscription(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        async with session_factory() as db:
            return await get_trial_winback_discount(db, await db.get(User, user_id))

    assert asyncio.run(scenario()) == (0, None)


# --- выбор лучшей скидки -------------------------------------------------------


async def _make_group(factory, percent: int) -> int:
    async with factory() as db:
        group = PromoGroup(name=f'g{percent}', discount_percent=percent)
        db.add(group)
        await db.commit()
        return group.id


def _best(session_factory, *, group=None, sale=None, trial_ended_ago=None):
    async def scenario():
        group_id = await _make_group(session_factory, group) if group is not None else None
        user_id = await make_user(session_factory, promo_group_id=group_id)
        if trial_ended_ago is not None:
            tariff_id = await make_tariff(session_factory)
            async with session_factory() as db:
                db.add(Subscription(user_id=user_id, tariff_id=tariff_id, status='expired', is_trial=True, end_date=NOW() - trial_ended_ago))
                await db.commit()
        async with session_factory() as db:
            if sale is not None:
                await _set_sale(db, str(sale), (NOW() + timedelta(days=3)).isoformat())
                await db.commit()
            return await get_best_discount(db, await db.get(User, user_id))

    return asyncio.run(scenario())


def test_no_discounts(session_factory):
    assert _best(session_factory) == (0, None)


def test_promo_group_discount_has_no_deadline(session_factory):
    assert _best(session_factory, group=15) == (15, None)


def test_sale_wins_over_smaller_group_discount_and_has_deadline(session_factory):
    percent, deadline = _best(session_factory, group=10, sale=30)

    assert percent == 30 and deadline is not None


def test_group_wins_over_smaller_sale_and_deadline_is_dropped(session_factory):
    assert _best(session_factory, group=40, sale=30) == (40, None)


def test_discounts_are_not_stacked(session_factory):
    """10% группа + 10% акция = 10%, а не 20% и не 19%."""
    percent, _ = _best(session_factory, group=10, sale=10)

    assert percent == 10


def test_winback_wins_over_smaller_sale(session_factory):
    percent, deadline = _best(session_factory, sale=15, trial_ended_ago=timedelta(hours=2))

    assert percent == TRIAL_WINBACK_DISCOUNT_PERCENT and deadline is not None


def test_missing_promo_group_row_means_no_group_discount(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            user.promo_group_id = 999  # группу удалили, а ссылка осталась
            return await get_best_discount(db, user)

    assert asyncio.run(scenario()) == (0, None)


# --- итоговые цены -------------------------------------------------------------


def test_period_and_daily_price_use_discount(session_factory):
    async def scenario():
        group_id = await _make_group(session_factory, 20)
        user_id = await make_user(session_factory, promo_group_id=group_id)
        tariff_id = await make_tariff(session_factory, period_prices_kopeks={'30': 30000, '90': 80000})
        async with session_factory() as db:
            from app.database.models import Tariff

            user, tariff = await db.get(User, user_id), await db.get(Tariff, tariff_id)
            return (
                await get_period_price_kopeks(db, tariff, 30, user),
                await get_period_price_kopeks(db, tariff, 90, user),
                await get_daily_price_kopeks(db, tariff, user),
            )

    month, quarter, daily = asyncio.run(scenario())

    assert month == 24000  # 300 ₽ - 20%
    assert quarter == 64000  # 800 ₽ - 20%
    assert daily == 24000 / 30
