"""Тесты app/services/promocode_service.py::activate_promocode на SQLite.

Не покрыто: гонка "два разных пользователя одновременно занимают последнюю
активацию" — защита там держится на SELECT ... FOR UPDATE, который SQLite
игнорирует; проверять это нужно на Postgres."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.database.models import PromoCode, PromoCodeUse, Subscription, User
from app.services.promocode_service import PromoCodeError, activate_promocode
from tests.helpers import make_tariff, make_user


async def _make_promo(factory, code='SUMMER', **fields) -> int:
    defaults = dict(type='balance', value=5000, max_activations=10)
    async with factory() as db:
        promo = PromoCode(code=code, **{**defaults, **fields})
        db.add(promo)
        await db.commit()
        return promo.id


async def _activate(factory, user_id: int, code: str):
    async with factory() as db:
        user = await db.get(User, user_id)
        try:
            result = await activate_promocode(db, code=code, user=user)
        except PromoCodeError:
            await db.rollback()
            raise
        await db.commit()
        return result


def test_balance_promo_credits_and_records_use(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=100)
        promo_id = await _make_promo(session_factory, value=5000)

        result = await _activate(session_factory, user_id, 'SUMMER')

        assert (result.type, result.value) == ('balance', 5000)
        async with session_factory() as db:
            assert (await db.get(User, user_id)).balance_kopeks == 5100
            promo = await db.get(PromoCode, promo_id)
            assert promo.activations_count == 1
            uses = await db.scalar(select(func.count()).select_from(PromoCodeUse))
            assert uses == 1

    asyncio.run(scenario())


def test_code_is_normalized(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        await _make_promo(session_factory, code='SUMMER')
        await _activate(session_factory, user_id, '  summer ')

    asyncio.run(scenario())


def test_days_promo_creates_subscription(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        await make_tariff(session_factory)
        await _make_promo(session_factory, type='days', value=7)

        before = datetime.now(timezone.utc)
        await _activate(session_factory, user_id, 'SUMMER')

        async with session_factory() as db:
            sub = (await db.execute(select(Subscription).where(Subscription.user_id == user_id))).scalar_one()
            end = sub.end_date if sub.end_date.tzinfo else sub.end_date.replace(tzinfo=timezone.utc)
            assert timedelta(days=6, hours=23) < end - before < timedelta(days=7, hours=1)

    asyncio.run(scenario())


def test_days_promo_without_active_tariff_fails_and_rolls_back(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        promo_id = await _make_promo(session_factory, type='days', value=7)

        with pytest.raises(PromoCodeError):
            await _activate(session_factory, user_id, 'SUMMER')

        async with session_factory() as db:
            assert (await db.get(PromoCode, promo_id)).activations_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    'promo_fields, code',
    [
        ({}, 'NOPE'),
        ({'is_active': False}, 'SUMMER'),
        ({'expires_at': datetime.now(timezone.utc) - timedelta(days=1)}, 'SUMMER'),
        ({'max_activations': 1, 'activations_count': 1}, 'SUMMER'),
        ({'type': 'weird'}, 'SUMMER'),
    ],
    ids=['not_found', 'inactive', 'expired', 'limit_reached', 'unknown_type'],
)
def test_invalid_promo_is_rejected_without_side_effects(session_factory, promo_fields, code):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=100)
        await _make_promo(session_factory, **promo_fields)

        with pytest.raises(PromoCodeError):
            await _activate(session_factory, user_id, code)

        async with session_factory() as db:
            assert (await db.get(User, user_id)).balance_kopeks == 100

    asyncio.run(scenario())


def test_same_user_cannot_activate_twice(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        await _make_promo(session_factory, value=5000)
        await _activate(session_factory, user_id, 'SUMMER')

        with pytest.raises(PromoCodeError, match='уже использовали'):
            await _activate(session_factory, user_id, 'SUMMER')

        async with session_factory() as db:
            assert (await db.get(User, user_id)).balance_kopeks == 5000

    asyncio.run(scenario())


def test_activation_limit_is_enforced_across_users(session_factory):
    async def scenario():
        first = await make_user(session_factory, telegram_id=1)
        second = await make_user(session_factory, telegram_id=2)
        await _make_promo(session_factory, max_activations=1)

        await _activate(session_factory, first, 'SUMMER')
        with pytest.raises(PromoCodeError, match='Лимит'):
            await _activate(session_factory, second, 'SUMMER')

    asyncio.run(scenario())
