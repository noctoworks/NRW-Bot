"""app/services/tariff_change_service.py — пропорциональный пересчёт при смене тарифа.

Доплата = (цена дня нового тарифа - цена дня старого) * оставшиеся дни; апгрейд
платный, даунгрейд бесплатный (остаток не возвращается), срок не меняется."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.database.models import PromoGroup, Subscription, Tariff, Transaction, User
from app.services import tariff_change_service
from app.services.balance_service import InsufficientBalanceError
from app.services.tariff_change_service import apply_tariff_change, compute_change_price_kopeks, remaining_days
from tests.helpers import make_tariff, make_user


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- remaining_days ------------------------------------------------------------


def _sub(end_date: datetime) -> Subscription:
    return Subscription(end_date=end_date)


def test_remaining_days_floors_partial_days():
    assert remaining_days(_sub(_now() + timedelta(days=3, hours=23))) == 3


def test_remaining_days_is_zero_for_expired():
    assert remaining_days(_sub(_now() - timedelta(days=5))) == 0
    assert remaining_days(_sub(_now() - timedelta(minutes=1))) == 0


def test_remaining_days_accepts_naive_datetimes_as_utc():
    """SQLite отдаёт даты без tzinfo."""
    naive_end = (_now() + timedelta(days=2, hours=1)).replace(tzinfo=None)

    assert remaining_days(_sub(naive_end)) == 2


# --- расчёт цены ---------------------------------------------------------------


async def _setup(factory, *, old_month: int, new_month: int, days_left: int | None, group_percent: int | None = None):
    """(user_id, subscription_id, old_tariff_id, new_tariff_id)."""
    group_id = None
    if group_percent is not None:
        async with factory() as db:
            group = PromoGroup(name='g', discount_percent=group_percent)
            db.add(group)
            await db.commit()
            group_id = group.id
    user_id = await make_user(factory, promo_group_id=group_id, balance_kopeks=100000)
    old_id = await make_tariff(
        factory, name='Базовый', period_prices_kopeks={'30': old_month}, traffic_limit_gb=100, device_limit=3, squad_uuids=['s-old']
    )
    new_id = await make_tariff(
        factory, name='Семейный', period_prices_kopeks={'30': new_month}, traffic_limit_gb=0, device_limit=10, squad_uuids=['s-new']
    )
    end = _now() + (timedelta(days=days_left, hours=1) if days_left is not None else timedelta(days=-1))
    async with factory() as db:
        subscription = Subscription(user_id=user_id, tariff_id=old_id, status='active', end_date=end, traffic_limit_gb=100, device_limit=3)
        db.add(subscription)
        await db.commit()
        return user_id, subscription.id, old_id, new_id


def _price(factory, **kwargs) -> int:
    async def scenario():
        user_id, sub_id, old_id, new_id = await _setup(factory, **kwargs)
        async with factory() as db:
            return await compute_change_price_kopeks(
                db,
                subscription=await db.get(Subscription, sub_id),
                current_tariff=await db.get(Tariff, old_id),
                new_tariff=await db.get(Tariff, new_id),
                user=await db.get(User, user_id),
            )

    return asyncio.run(scenario())


def test_upgrade_price_is_daily_difference_times_remaining_days(session_factory):
    # 300 ₽/мес -> 600 ₽/мес: 10 ₽/день -> 20 ₽/день, 10 дней: (20 - 10) * 10 = 100 ₽
    assert _price(session_factory, old_month=30000, new_month=60000, days_left=10) == 10000


def test_price_is_rounded_to_nearest_kopek(session_factory):
    # 100 ₽ -> 150 ₽ за 30 дней: (500 - 333.33) * 10 = 1666.67 коп. -> 1667
    assert _price(session_factory, old_month=10000, new_month=15000, days_left=10) == 1667


def test_downgrade_is_free(session_factory):
    assert _price(session_factory, old_month=60000, new_month=30000, days_left=10) == 0


def test_same_price_is_free(session_factory):
    assert _price(session_factory, old_month=30000, new_month=30000, days_left=10) == 0


def test_expired_subscription_costs_nothing(session_factory):
    assert _price(session_factory, old_month=30000, new_month=60000, days_left=None) == 0


def test_promo_group_discount_applies_to_both_tariffs(session_factory):
    # с -50%: 150 ₽ и 300 ₽ за месяц -> 5 ₽/день и 10 ₽/день, 10 дней = 50 ₽
    assert _price(session_factory, old_month=30000, new_month=60000, days_left=10, group_percent=50) == 5000


# --- применение ----------------------------------------------------------------


def _apply(factory, *, balance: int, price: int, remnawave_uuid: str | None = None, monkeypatch=None, client=None):
    async def scenario():
        user_id, sub_id, old_id, new_id = await _setup(factory, old_month=30000, new_month=60000, days_left=10)
        async with factory() as db:
            user = await db.get(User, user_id)
            user.balance_kopeks = balance
            user.remnawave_uuid = remnawave_uuid
            await db.commit()
        if client is not None:
            monkeypatch.setattr(tariff_change_service, 'get_remnawave_client', lambda: client)

        async with factory() as db:
            user = await db.get(User, user_id)
            subscription = await db.get(Subscription, sub_id)
            end_before = subscription.end_date
            error = None
            try:
                await apply_tariff_change(
                    db, user=user, subscription=subscription, new_tariff=await db.get(Tariff, new_id), price_kopeks=price
                )
                await db.commit()
            except InsufficientBalanceError as caught:
                error = caught
                await db.rollback()

        async with factory() as db:
            subscription = await db.get(Subscription, sub_id)
            return SimpleNamespace(
                error=error,
                new_id=new_id,
                old_id=old_id,
                end_before=end_before,
                subscription=subscription,
                balance=(await db.get(User, user_id)).balance_kopeks,
                transactions=(await db.execute(select(Transaction).where(Transaction.user_id == user_id))).scalars().all(),
            )

    return asyncio.run(scenario())


def test_upgrade_debits_balance_records_transaction_and_switches_tariff(session_factory):
    result = _apply(session_factory, balance=50000, price=10000)

    assert result.error is None
    assert result.balance == 40000
    (transaction,) = result.transactions
    assert (transaction.type, transaction.amount_kopeks, transaction.status) == ('subscription_payment', 10000, 'completed')
    assert 'Семейный' in transaction.description
    sub = result.subscription
    assert sub.tariff_id == result.new_id and sub.device_limit == 10 and sub.traffic_limit_gb == 0
    assert sub.end_date == result.end_before  # срок не меняется


def test_free_change_touches_no_money_but_switches_tariff(session_factory):
    result = _apply(session_factory, balance=500, price=0)

    assert result.balance == 500 and result.transactions == []
    assert result.subscription.tariff_id == result.new_id


def test_insufficient_balance_changes_nothing(session_factory):
    result = _apply(session_factory, balance=3000, price=10000)

    assert result.error is not None and result.error.missing_kopeks == 7000
    assert result.balance == 3000 and result.transactions == []
    assert result.subscription.tariff_id == result.old_id and result.subscription.device_limit == 3


def test_panel_gets_same_expiry_with_new_limits(session_factory, monkeypatch):
    client = SimpleNamespace(extend_user_expiration=AsyncMock())

    result = _apply(session_factory, balance=50000, price=10000, remnawave_uuid='rw-1', monkeypatch=monkeypatch, client=client)

    client.extend_user_expiration.assert_awaited_once()
    kwargs = client.extend_user_expiration.await_args.kwargs
    assert kwargs['remnawave_uuid'] == 'rw-1'
    assert kwargs['expire_at'].replace(tzinfo=None) == result.end_before.replace(tzinfo=None)
    assert kwargs['traffic_limit_gb'] == 0 and kwargs['squad_uuids'] == ['s-new']


def test_user_without_panel_account_skips_panel_call(session_factory, monkeypatch):
    client = SimpleNamespace(extend_user_expiration=AsyncMock())

    _apply(session_factory, balance=50000, price=10000, remnawave_uuid=None, monkeypatch=monkeypatch, client=client)

    client.extend_user_expiration.assert_not_awaited()
