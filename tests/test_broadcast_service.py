"""broadcast_service: одна рассылка одновременно, прогресс, отмена, восстановление после
рестарта. Поведение самой отправки (батчи/ретраи/медиа) уже покрыто tests/test_broadcast_golden.py
через run_broadcast_now — здесь проверяется то, что golden-тесты не видят: start_broadcast
(фоновая задача), cancel_broadcast, mark_interrupted_broadcasts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.database.models import BroadcastHistory, User
from app.services import broadcast_service as bs
from tests.helpers import make_user


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(bs, 'AsyncSessionLocal', session_factory)
    yield
    bs._cancel_flags.clear()


async def _await_background_tasks() -> None:
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


def test_start_broadcast_returns_immediately_and_finishes_in_background(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=1, is_admin=True)
        await make_user(session_factory, telegram_id=2)
        await make_user(session_factory, telegram_id=3)
        bot = AsyncMock()

        async with session_factory() as db:
            admin = await db.get(User, admin_id)
            history = await bs.start_broadcast(db, bot, admin=admin, target='all', text='Привет')
            assert history.status == 'in_progress'
            # 'all' включает и самого админа (см. tests/test_broadcast_golden.py) — 3 пользователя.
            assert history.total_count == 3

        await _await_background_tasks()

        async with session_factory() as db:
            row = await db.get(BroadcastHistory, history.id)
            assert row.status == 'completed'
            assert row.sent_count == 3

    asyncio.run(scenario())


def test_second_broadcast_is_rejected_while_first_is_in_progress(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=1, is_admin=True)
        async with session_factory() as db:
            db.add(BroadcastHistory(target_type='all', message_text='x', total_count=0, status='in_progress'))
            await db.commit()

        async with session_factory() as db:
            admin = await db.get(User, admin_id)
            with pytest.raises(bs.BroadcastAlreadyRunningError):
                await bs.start_broadcast(db, AsyncMock(), admin=admin, target='all', text='Второй')

    asyncio.run(scenario())


def test_cancel_before_the_loop_starts_sends_nothing(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=1, is_admin=True)
        for tg_id in range(2, 7):
            await make_user(session_factory, telegram_id=tg_id)
        bot = AsyncMock()

        async with session_factory() as db:
            admin = await db.get(User, admin_id)
            history = await bs.start_broadcast(db, bot, admin=admin, target='all', text='Отменённая')
            await bs.cancel_broadcast(db, history.id)

        await _await_background_tasks()

        async with session_factory() as db:
            row = await db.get(BroadcastHistory, history.id)
            assert row.status == 'cancelled'
            assert row.sent_count == 0
        bot.send_message.assert_not_awaited()

    asyncio.run(scenario())


def test_cancel_unknown_broadcast_raises_not_found(session_factory):
    async def scenario():
        async with session_factory() as db:
            with pytest.raises(bs.BroadcastNotFoundError):
                await bs.cancel_broadcast(db, 999999)

    asyncio.run(scenario())


def test_cancel_already_finished_broadcast_raises_not_running(session_factory):
    async def scenario():
        async with session_factory() as db:
            history = BroadcastHistory(target_type='all', message_text='x', total_count=0, status='completed')
            db.add(history)
            await db.commit()
            await db.refresh(history)
            with pytest.raises(bs.BroadcastNotRunningError):
                await bs.cancel_broadcast(db, history.id)

    asyncio.run(scenario())


def test_run_broadcast_now_waits_for_completion_and_returns_final_row(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=1, is_admin=True)
        await make_user(session_factory, telegram_id=2)
        bot = AsyncMock()

        async with session_factory() as db:
            admin = await db.get(User, admin_id)
            history = await bs.run_broadcast_now(db, bot, admin=admin, target='all', text='Синхронно')
            assert history.status == 'completed'
            # 'all' включает и самого админа — 2 пользователя (см. tests/test_broadcast_golden.py).
            assert history.sent_count == 2

    asyncio.run(scenario())


def test_mark_interrupted_broadcasts_marks_stale_in_progress_rows(session_factory):
    async def scenario():
        async with session_factory() as db:
            db.add(BroadcastHistory(target_type='all', message_text='x', total_count=1, status='in_progress'))
            db.add(BroadcastHistory(target_type='all', message_text='y', total_count=1, status='completed'))
            await db.commit()

        count = await bs.mark_interrupted_broadcasts()
        assert count == 1

        async with session_factory() as db:
            rows = (await db.execute(__import__('sqlalchemy').select(BroadcastHistory))).scalars().all()
            statuses = sorted(r.status for r in rows)
            assert statuses == ['completed', 'interrupted']

    asyncio.run(scenario())
