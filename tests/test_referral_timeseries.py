"""Динамика рефералов по дням: GET /cabinet/admin/referrals/timeseries.

Формулы (см. ТЗ): invited — рефералы по User.created_at; paid_first — рефералы, чей ПЕРВЫЙ платёж
(REVENUE_TYPES, completed, не с баланса — те же правила, что у referred_paying_count) пришёлся на день;
earnings_kopeks — сумма ReferralEarning по дню. Границы дней — UTC, ровно N точек, последняя — сегодня."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cabinet.admin_deps import require_admin
from app.cabinet.app import create_app
from app.cabinet.deps import get_db
from app.database.models import Payment, ReferralEarning, Transaction, User
from app.services import analytics_service
from tests.helpers import make_user

NOW = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
BASE = '/cabinet/admin/referrals/timeseries'


def _at(day: int, hour: int = 12, minute: int = 0, second: int = 0) -> datetime:
    """Момент внутри сентября 2026 (UTC)."""
    return datetime(2026, 9, day, hour, minute, second, tzinfo=timezone.utc)


async def _referrer(factory) -> int:
    return await make_user(factory, telegram_id=1000, referral_code='boss')


async def _referral(factory, referrer_id: int, telegram_id: int, created_at: datetime) -> int:
    return await make_user(factory, telegram_id=telegram_id, referred_by_id=referrer_id, created_at=created_at)


async def _payment(
    factory, user_id: int, created_at: datetime, *, type: str = 'subscription_payment', status: str = 'completed',
    provider: str | None = 'stub', amount: int = 10000,
) -> None:
    """Транзакция + (по умолчанию) платёж провайдера. provider='balance' — оплата с баланса, None — без Payment."""
    async with factory() as db:
        transaction = Transaction(user_id=user_id, type=type, amount_kopeks=amount, status=status, created_at=created_at)
        db.add(transaction)
        await db.flush()
        if provider is not None:
            db.add(Payment(
                user_id=user_id, transaction_id=transaction.id, provider=provider,
                external_id=f'ext-{transaction.id}', amount_kopeks=amount, status='success',
            ))
        await db.commit()


async def _earning(factory, referrer_id: int, source_id: int, created_at: datetime, amount: int) -> None:
    async with factory() as db:
        db.add(ReferralEarning(
            user_id=referrer_id, source_user_id=source_id, amount_kopeks=amount, source='purchase', created_at=created_at,
        ))
        await db.commit()


async def _series(factory, *, days: int) -> dict:
    async with factory() as db:
        return await analytics_service.get_referral_timeseries(db, days=days, now=NOW)


def _by_date(result: dict) -> dict:
    return {point['date']: point for point in result['points']}


def test_day_without_events_is_zeros_and_series_has_exactly_n_ascending_points(session_factory):
    async def scenario():
        result = await _series(session_factory, days=3)
        assert result['days'] == 3
        assert result['points'] == [
            {'date': '2026-09-22', 'invited': 0, 'paid_first': 0, 'earnings_kopeks': 0},
            {'date': '2026-09-23', 'invited': 0, 'paid_first': 0, 'earnings_kopeks': 0},
            {'date': '2026-09-24', 'invited': 0, 'paid_first': 0, 'earnings_kopeks': 0},
        ]

    asyncio.run(scenario())


def test_days_one_is_only_today_and_days_boundaries_are_calendar_utc_days(session_factory):
    async def scenario():
        referrer = await _referrer(session_factory)
        await _referral(session_factory, referrer, 1, _at(23, 23, 59, 59))  # вчера, за секунду до полуночи
        await _referral(session_factory, referrer, 2, _at(24, 0, 0, 0))  # ровно полночь — уже сегодня

        one = await _series(session_factory, days=1)
        assert [(p['date'], p['invited']) for p in one['points']] == [('2026-09-24', 1)]

        two = await _series(session_factory, days=2)
        assert [(p['date'], p['invited']) for p in two['points']] == [('2026-09-23', 1), ('2026-09-24', 1)]

    asyncio.run(scenario())


def test_invited_counts_only_referred_users_created_inside_the_window(session_factory):
    async def scenario():
        referrer = await _referrer(session_factory)
        await _referral(session_factory, referrer, 1, _at(22))
        await _referral(session_factory, referrer, 2, _at(22, 18))
        await _referral(session_factory, referrer, 3, _at(24))
        await _referral(session_factory, referrer, 4, _at(10))  # до окна
        await make_user(session_factory, telegram_id=5, created_at=_at(22))  # не реферал

        points = _by_date(await _series(session_factory, days=3))
        assert [points[d]['invited'] for d in ('2026-09-22', '2026-09-23', '2026-09-24')] == [2, 0, 1]

    asyncio.run(scenario())


def test_referral_with_several_payments_is_paid_first_once_on_the_day_of_the_first_payment(session_factory):
    async def scenario():
        referrer = await _referrer(session_factory)
        user = await _referral(session_factory, referrer, 1, _at(1))
        await _payment(session_factory, user, _at(23, 9))
        await _payment(session_factory, user, _at(24, 9))
        await _payment(session_factory, user, _at(22, 9))  # самый ранний — вставлен не первым

        points = _by_date(await _series(session_factory, days=5))
        assert {d: p['paid_first'] for d, p in points.items()} == {
            '2026-09-20': 0, '2026-09-21': 0, '2026-09-22': 1, '2026-09-23': 0, '2026-09-24': 0,
        }

    asyncio.run(scenario())


def test_first_payment_before_the_window_is_not_counted_even_if_later_payments_are_inside(session_factory):
    async def scenario():
        referrer = await _referrer(session_factory)
        user = await _referral(session_factory, referrer, 1, _at(1))
        await _payment(session_factory, user, _at(5))  # первый — до окна
        await _payment(session_factory, user, _at(23))  # повторный — внутри окна, но «первым» не является

        points = (await _series(session_factory, days=3))['points']
        assert sum(p['paid_first'] for p in points) == 0

    asyncio.run(scenario())


def test_payments_that_do_not_count_as_paying_are_ignored_for_paid_first(session_factory):
    async def scenario():
        referrer = await _referrer(session_factory)
        user = await _referral(session_factory, referrer, 1, _at(1))
        await _payment(session_factory, user, _at(22), provider='balance')  # оплата с баланса — не новые деньги
        await _payment(session_factory, user, _at(22, 13), status='failed')
        await _payment(session_factory, user, _at(22, 14), type='referral_reward', provider=None)
        await _payment(session_factory, user, _at(23), provider='platega')  # первый настоящий платёж

        points = _by_date(await _series(session_factory, days=3))
        assert points['2026-09-22']['paid_first'] == 0
        assert points['2026-09-23']['paid_first'] == 1

    asyncio.run(scenario())


def test_gift_counts_as_paying_and_payer_who_is_not_a_referral_is_ignored(session_factory):
    async def scenario():
        referrer = await _referrer(session_factory)
        gifter = await _referral(session_factory, referrer, 1, _at(1))
        stranger = await make_user(session_factory, telegram_id=2)
        await _payment(session_factory, gifter, _at(23), type='gift')
        await _payment(session_factory, stranger, _at(23))

        points = _by_date(await _series(session_factory, days=2))
        assert points['2026-09-23']['paid_first'] == 1

    asyncio.run(scenario())


def test_earnings_are_summed_per_day_in_kopeks_and_outside_window_is_ignored(session_factory):
    async def scenario():
        referrer = await _referrer(session_factory)
        source = await _referral(session_factory, referrer, 1, _at(1))
        await _earning(session_factory, referrer, source, _at(22, 8), 1490)
        await _earning(session_factory, referrer, source, _at(22, 20), 510)
        await _earning(session_factory, referrer, source, _at(24), 700)
        await _earning(session_factory, referrer, source, _at(5), 99999)  # до окна

        points = _by_date(await _series(session_factory, days=3))
        assert [points[d]['earnings_kopeks'] for d in ('2026-09-22', '2026-09-23', '2026-09-24')] == [2000, 0, 700]

    asyncio.run(scenario())


def test_invariants_against_the_all_time_funnel(session_factory):
    async def scenario():
        referrer = await _referrer(session_factory)
        inside = await _referral(session_factory, referrer, 1, _at(23))
        outside = await _referral(session_factory, referrer, 2, _at(2))
        await _payment(session_factory, inside, _at(23, 13))
        await _payment(session_factory, outside, _at(3))
        await _earning(session_factory, referrer, inside, _at(23, 13), 1000)
        await _earning(session_factory, referrer, outside, _at(3), 500)

        result = await _series(session_factory, days=7)
        async with session_factory() as db:
            funnel = await analytics_service.get_referral_funnel(db)

        assert sum(p['invited'] for p in result['points']) <= funnel['referred_users_count']
        assert sum(p['earnings_kopeks'] for p in result['points']) <= funnel['total_earnings_kopeks']
        assert sum(p['paid_first'] for p in result['points']) <= funnel['referred_paying_count']
        assert (sum(p['invited'] for p in result['points']), sum(p['paid_first'] for p in result['points'])) == (1, 1)
        assert sum(p['earnings_kopeks'] for p in result['points']) == 1000

    asyncio.run(scenario())


# --- HTTP ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def api(session_factory):
    admin_id = asyncio.run(make_user(session_factory, telegram_id=555, username='boss', is_admin=True))
    engine = create_async_engine(str(session_factory.kw['bind'].url), connect_args={'timeout': 30})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app = create_app(AsyncMock())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: User(id=admin_id, telegram_id=555, referral_code='a', is_admin=True)
    with TestClient(app) as client:
        yield client


def test_endpoint_defaults_to_30_points_ending_today_with_the_documented_shape(api):
    response = api.get(BASE)

    assert response.status_code == 200
    body = response.json()
    assert body['days'] == 30
    assert len(body['points']) == 30
    assert set(body['points'][0]) == {'date', 'invited', 'paid_first', 'earnings_kopeks'}
    today = datetime.now(timezone.utc).date()
    dates = [point['date'] for point in body['points']]
    assert dates == [(today - timedelta(days=offset)).isoformat() for offset in range(29, -1, -1)]


@pytest.mark.parametrize('days', [1, 365])
def test_endpoint_accepts_boundary_days(api, days):
    response = api.get(BASE, params={'days': days})

    assert response.status_code == 200
    assert response.json()['days'] == days
    assert len(response.json()['points']) == days


@pytest.mark.parametrize('days', [0, -1, 366, 800])
def test_endpoint_rejects_days_out_of_range(api, days):
    assert api.get(BASE, params={'days': days}).status_code == 422


def test_endpoint_requires_admin():
    with TestClient(create_app(AsyncMock())) as client:
        assert client.get(BASE).status_code == 401
