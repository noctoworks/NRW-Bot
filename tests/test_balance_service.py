"""Тесты app/services/balance_service.py на SQLite (файловая БД во временном
каталоге, чтобы несколько сессий видели одни данные). SELECT ... FOR UPDATE
SQLite игнорирует, поэтому проверяется логика и атомарность UPDATE, а не
блокировки Postgres."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.models import Base, User
from app.services.balance_service import (
    InsufficientBalanceError,
    adjust_balance_clamped,
    credit_balance,
    debit_balance,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "test.db"}', connect_args={'timeout': 30})

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _make_user(factory, balance: int = 0) -> int:
    async with factory() as db:
        user = User(telegram_id=1, referral_code='ref1', balance_kopeks=balance)
        db.add(user)
        await db.commit()
        return user.id


async def _stored_balance(factory, user_id: int) -> int:
    async with factory() as db:
        return (await db.get(User, user_id)).balance_kopeks


def test_credit_updates_db_and_object(session_factory):
    async def scenario():
        user_id = await _make_user(session_factory, 100)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            await credit_balance(db, user, 250)
            assert user.balance_kopeks == 350
            await db.commit()
        assert await _stored_balance(session_factory, user_id) == 350

    asyncio.run(scenario())


def test_credit_zero_is_noop_and_negative_rejected(session_factory):
    async def scenario():
        user_id = await _make_user(session_factory, 100)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            await credit_balance(db, user, 0)
            assert user.balance_kopeks == 100
            with pytest.raises(ValueError):
                await credit_balance(db, user, -1)

    asyncio.run(scenario())


def test_debit_exact_amount(session_factory):
    async def scenario():
        user_id = await _make_user(session_factory, 300)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            await debit_balance(db, user, 300)
            assert user.balance_kopeks == 0
            await db.commit()
        assert await _stored_balance(session_factory, user_id) == 0

    asyncio.run(scenario())


def test_debit_insufficient_raises_and_keeps_balance(session_factory):
    async def scenario():
        user_id = await _make_user(session_factory, 300)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            with pytest.raises(InsufficientBalanceError) as exc_info:
                await debit_balance(db, user, 400)
            assert exc_info.value.missing_kopeks == 100
            assert user.balance_kopeks == 300
            await db.commit()
        assert await _stored_balance(session_factory, user_id) == 300

    asyncio.run(scenario())


def test_debit_uses_db_value_not_stale_object(session_factory):
    """Объект User устарел (баланс в БД уже уменьшили в другой сессии) —
    списание должно смотреть в БД, а не в кэш объекта."""

    async def scenario():
        user_id = await _make_user(session_factory, 500)
        async with session_factory() as stale_db:
            stale_user = await stale_db.get(User, user_id)  # видит 500
            async with session_factory() as other:
                other_user = await other.get(User, user_id)
                await debit_balance(other, other_user, 450)
                await other.commit()
            with pytest.raises(InsufficientBalanceError):
                await debit_balance(stale_db, stale_user, 400)

    asyncio.run(scenario())


def test_clamped_debit_stops_at_zero(session_factory):
    async def scenario():
        user_id = await _make_user(session_factory, 300)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            assert await adjust_balance_clamped(db, user, -1000) == -300
            assert user.balance_kopeks == 0
            assert await adjust_balance_clamped(db, user, -1) == 0
            await db.commit()
        assert await _stored_balance(session_factory, user_id) == 0

    asyncio.run(scenario())


def test_clamped_credit_and_partial_debit(session_factory):
    async def scenario():
        user_id = await _make_user(session_factory, 100)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            assert await adjust_balance_clamped(db, user, 50) == 50
            assert await adjust_balance_clamped(db, user, -30) == -30
            assert user.balance_kopeks == 120
            await db.commit()
        assert await _stored_balance(session_factory, user_id) == 120

    asyncio.run(scenario())


def test_concurrent_credits_are_not_lost(session_factory):
    """Раньше `user.balance_kopeks += x` в разных сессиях затирал часть начислений."""

    async def one_credit(user_id: int) -> None:
        async with session_factory() as db:
            user = await db.get(User, user_id)
            await credit_balance(db, user, 100)
            await db.commit()

    async def scenario():
        user_id = await _make_user(session_factory, 0)
        await asyncio.gather(*(one_credit(user_id) for _ in range(20)))
        assert await _stored_balance(session_factory, user_id) == 2000

    asyncio.run(scenario())


def test_concurrent_debits_never_overspend(session_factory):
    """Баланса хватает на 3 списания по 100 из 10 параллельных — ровно 3 успешных."""

    async def one_debit(user_id: int) -> bool:
        async with session_factory() as db:
            user = await db.get(User, user_id)
            try:
                await debit_balance(db, user, 100)
            except InsufficientBalanceError:
                return False
            await db.commit()
            return True

    async def scenario():
        user_id = await _make_user(session_factory, 300)
        results = await asyncio.gather(*(one_debit(user_id) for _ in range(10)))
        assert sum(results) == 3
        assert await _stored_balance(session_factory, user_id) == 0

    asyncio.run(scenario())
