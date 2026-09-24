"""Поиск пользователей в админке: по Telegram ID, username И имени (full_name) — во всех трёх списках
(/users, /subscriptions, /transactions).

Регистр: на PostgreSQL ILIKE нечувствителен к регистру и для кириллицы, на SQLite (dev/тесты) — только для
ASCII, поэтому кириллические проверки здесь идут в исходном регистре."""

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
from app.database.models import Subscription, Transaction, User
from tests.helpers import make_tariff, make_user

BASE = '/cabinet/admin'


@pytest.fixture
def api(session_factory):
    asyncio.run(_seed(session_factory))
    engine = create_async_engine(str(session_factory.kw['bind'].url), connect_args={'timeout': 30})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app = create_app(AsyncMock())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: User(id=1, telegram_id=1, referral_code='a', is_admin=True)
    with TestClient(app) as client:
        yield client


async def _seed(factory) -> None:
    """Четыре пользователя: у каждого подписка и транзакция, чтобы находить их во всех трёх списках."""
    tariff_id = await make_tariff(factory)
    people = [
        (101, 'ivan_petrov', 'Иван Петров'),
        (102, 'anna', 'Анна Сидорова'),
        (103, None, 'Only Name'),  # без username — раньше по такому пользователю поиск не находил ничего
        (104, 'zed', 'Peter Petrovich'),
    ]
    for telegram_id, username, full_name in people:
        user_id = await make_user(factory, telegram_id=telegram_id, username=username, full_name=full_name)
        async with factory() as db:
            db.add(Subscription(
                user_id=user_id, tariff_id=tariff_id, status='active', end_date=datetime.now(timezone.utc) + timedelta(days=5),
            ))
            db.add(Transaction(user_id=user_id, type='subscription_payment', amount_kopeks=10000, status='completed'))
            await db.commit()


def _user_ids_users(api, query: str) -> set[int]:
    return {item['telegram_id'] for item in api.get(f'{BASE}/users', params={'query': query}).json()['items']}


def _user_ids_subscriptions(api, query: str) -> set[int]:
    body = api.get(f'{BASE}/subscriptions', params={'query': query}).json()
    return {item['telegram_id'] for item in body['items']}


def _user_ids_transactions(api, query: str) -> set[int]:
    body = api.get(f'{BASE}/transactions', params={'query': query}).json()
    return {item['telegram_id'] for item in body['items']}


LISTS = [_user_ids_users, _user_ids_subscriptions, _user_ids_transactions]
IDS = ['users', 'subscriptions', 'transactions']


@pytest.mark.parametrize('find', LISTS, ids=IDS)
def test_search_by_full_name_finds_the_user(api, find):
    assert find(api, 'Иван') == {101}
    assert find(api, 'Сидорова') == {102}


@pytest.mark.parametrize('find', LISTS, ids=IDS)
def test_search_by_name_works_for_a_user_without_username(api, find):
    assert find(api, 'Only') == {103}
    assert find(api, 'only name') == {103}  # ASCII: регистр не важен и на SQLite


@pytest.mark.parametrize('find', LISTS, ids=IDS)
def test_username_and_telegram_id_search_still_work(api, find):
    assert find(api, 'ivan_petrov') == {101}
    assert find(api, '@ivan_petrov') == {101}
    assert find(api, '102') == {102}


@pytest.mark.parametrize('find', LISTS, ids=IDS)
def test_query_can_match_username_of_one_user_and_name_of_another(api, find):
    # 'petro': username 'ivan_petrov' (101) и имя 'Peter Petrovich' (104) — условия объединяются через OR.
    assert find(api, 'petro') == {101, 104}
