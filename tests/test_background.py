"""app/services/background.py — поллинг платежей, истечение подписок, синхронизация трафика.

Не покрыто: реальная конкурентная работа с блокировками Postgres."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.database.models import Payment, Subscription, Transaction
from app.services import background
from tests.helpers import make_tariff, make_user


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(background, 'AsyncSessionLocal', session_factory)


class FakeProvider:
    """check_payment_status_detailed по external_id: 'success'|'failed'|'pending'|'hang'|'error'."""

    def __init__(self, statuses: dict[str, str]) -> None:
        self.statuses = statuses
        self.calls: list[str] = []

    async def check_payment_status_detailed(self, external_id: str, *, amount_kopeks=None):
        self.calls.append(external_id)
        status = self.statuses[external_id]
        if status == 'hang':
            await asyncio.sleep(3600)
        if status == 'error':
            raise RuntimeError('provider down')
        return status, {'status': status}


def _patch_provider(monkeypatch, statuses: dict[str, str]) -> FakeProvider:
    provider = FakeProvider(statuses)
    monkeypatch.setattr('app.services.payment.get_payment_provider', lambda name: provider)
    return provider


async def _add_payment(factory, user_id, tariff_id, external_id, age: timedelta = timedelta(minutes=5)) -> int:
    async with factory() as db:
        transaction = Transaction(user_id=user_id, type='subscription_payment', amount_kopeks=10000, status='pending')
        db.add(transaction)
        await db.flush()
        payment = Payment(
            user_id=user_id,
            transaction_id=transaction.id,
            provider='cispay',
            external_id=external_id,
            amount_kopeks=10000,
            status='pending',
            abandoned_reminder_sent=True,
            raw_payload={'kind': 'subscription', 'tariff_id': tariff_id, 'period_days': 30},
            created_at=datetime.now(timezone.utc) - age,
        )
        db.add(payment)
        await db.commit()
        return payment.id


async def _status(factory, payment_id) -> str:
    async with factory() as db:
        return (await db.get(Payment, payment_id)).status


# --- поллинг платежей ---------------------------------------------------------


def test_poll_finalizes_paid_and_fails_failed(session_factory, monkeypatch):
    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        paid = await _add_payment(session_factory, user_id, tariff_id, 'paid')
        failed = await _add_payment(session_factory, user_id, tariff_id, 'failed')
        waiting = await _add_payment(session_factory, user_id, tariff_id, 'waiting')
        _patch_provider(monkeypatch, {'paid': 'success', 'failed': 'failed', 'waiting': 'pending'})

        await background.run_payment_poll_once(AsyncMock())

        assert await _status(session_factory, paid) == 'success'
        assert await _status(session_factory, failed) == 'failed'
        assert await _status(session_factory, waiting) == 'pending'

    asyncio.run(scenario())


def test_hanging_provider_does_not_block_other_payments(session_factory, monkeypatch):
    monkeypatch.setattr(background, 'PAYMENT_CHECK_TIMEOUT_SECONDS', 0.2)

    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        stuck = await _add_payment(session_factory, user_id, tariff_id, 'stuck')
        paid = await _add_payment(session_factory, user_id, tariff_id, 'paid')
        _patch_provider(monkeypatch, {'stuck': 'hang', 'paid': 'success'})

        await asyncio.wait_for(background.run_payment_poll_once(AsyncMock()), timeout=5)

        assert await _status(session_factory, paid) == 'success'
        assert await _status(session_factory, stuck) == 'pending'

    asyncio.run(scenario())


def test_provider_error_leaves_payment_pending(session_factory, monkeypatch):
    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        payment_id = await _add_payment(session_factory, user_id, tariff_id, 'boom')
        _patch_provider(monkeypatch, {'boom': 'error'})

        await background.run_payment_poll_once(AsyncMock())

        assert await _status(session_factory, payment_id) == 'pending'

    asyncio.run(scenario())


def test_stale_payments_are_skipped_unless_requested(session_factory, monkeypatch):
    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        fresh = await _add_payment(session_factory, user_id, tariff_id, 'fresh')
        stale = await _add_payment(session_factory, user_id, tariff_id, 'stale', age=timedelta(days=2))
        provider = _patch_provider(monkeypatch, {'fresh': 'pending', 'stale': 'success'})

        await background.run_payment_poll_once(AsyncMock(), include_stale=False)
        assert provider.calls == ['fresh']
        assert await _status(session_factory, stale) == 'pending'

        await background.run_payment_poll_once(AsyncMock(), include_stale=True)
        assert 'stale' in provider.calls
        assert await _status(session_factory, stale) == 'success'
        assert await _status(session_factory, fresh) == 'pending'

    asyncio.run(scenario())


def test_payment_pending_beyond_max_age_is_marked_failed(session_factory, monkeypatch):
    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        ancient = await _add_payment(session_factory, user_id, tariff_id, 'ancient', age=timedelta(days=8))
        _patch_provider(monkeypatch, {'ancient': 'pending'})

        await background.run_payment_poll_once(AsyncMock(), include_stale=True)

        assert await _status(session_factory, ancient) == 'failed'

    asyncio.run(scenario())


def test_old_payment_that_was_actually_paid_is_still_finalized(session_factory, monkeypatch):
    """Даже спустя max_age провайдер — источник правды: оплаченное не теряем."""

    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        ancient = await _add_payment(session_factory, user_id, tariff_id, 'ancient', age=timedelta(days=8))
        _patch_provider(monkeypatch, {'ancient': 'success'})

        await background.run_payment_poll_once(AsyncMock(), include_stale=True)

        assert await _status(session_factory, ancient) == 'success'

    asyncio.run(scenario())


def test_poll_concurrency_is_bounded(session_factory, monkeypatch):
    monkeypatch.setattr(background, 'PAYMENT_POLL_CONCURRENCY', 2)
    running = 0
    peak = 0

    class Slow:
        async def check_payment_status_detailed(self, external_id, *, amount_kopeks=None):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1
            return 'pending', None

    monkeypatch.setattr('app.services.payment.get_payment_provider', lambda name: Slow())

    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        for i in range(6):
            await _add_payment(session_factory, user_id, tariff_id, f'p{i}')

        await background.run_payment_poll_once(AsyncMock())

    asyncio.run(scenario())
    assert peak == 2


# --- истечение подписок и трафик ----------------------------------------------


async def _add_subscription(factory, telegram_id: int, remnawave_uuid: str | None, *, expired: bool = True) -> int:
    user_id = await make_user(factory, telegram_id=telegram_id, remnawave_uuid=remnawave_uuid)
    tariff_id = await make_tariff(factory, name=f'T{telegram_id}')
    end = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(days=30))
    async with factory() as db:
        db.add(Subscription(user_id=user_id, tariff_id=tariff_id, status='active', end_date=end))
        await db.commit()
    return user_id


async def _sub_status(factory, user_id: int) -> str:
    async with factory() as db:
        return (await db.execute(select(Subscription.status).where(Subscription.user_id == user_id))).scalar_one()


def _patch_remnawave(monkeypatch, client) -> None:
    monkeypatch.setattr(background, 'get_remnawave_client', lambda: client)


def test_expiry_marks_expired_and_disables_in_remnawave(session_factory, monkeypatch):
    client = SimpleNamespace(disable_user=AsyncMock())
    _patch_remnawave(monkeypatch, client)
    bot = AsyncMock()

    async def scenario():
        user_id = await _add_subscription(session_factory, 1, 'uuid-1')
        await background.run_expiry_check_once(bot)
        assert await _sub_status(session_factory, user_id) == 'expired'

    asyncio.run(scenario())
    client.disable_user.assert_awaited_once_with(remnawave_uuid='uuid-1')


def test_failed_disable_keeps_subscription_active_for_retry(session_factory, monkeypatch):
    """Если панель не ответила — не помечаем expired: иначе отключение никто бы не повторил."""
    client = SimpleNamespace(disable_user=AsyncMock(side_effect=RuntimeError('panel down')))
    _patch_remnawave(monkeypatch, client)

    async def scenario():
        user_id = await _add_subscription(session_factory, 1, 'uuid-1')
        await background.run_expiry_check_once(AsyncMock())
        assert await _sub_status(session_factory, user_id) == 'active'

        client.disable_user = AsyncMock()  # панель поднялась
        await background.run_expiry_check_once(AsyncMock())
        assert await _sub_status(session_factory, user_id) == 'expired'

    asyncio.run(scenario())


def test_expiry_stops_calling_remnawave_after_consecutive_failures(session_factory, monkeypatch):
    client = SimpleNamespace(disable_user=AsyncMock(side_effect=RuntimeError('panel down')))
    _patch_remnawave(monkeypatch, client)

    async def scenario():
        for telegram_id in range(1, 9):
            await _add_subscription(session_factory, telegram_id, f'uuid-{telegram_id}')
        await background.run_expiry_check_once(AsyncMock())

    asyncio.run(scenario())
    assert client.disable_user.await_count == background.REMNAWAVE_MAX_CONSECUTIVE_FAILURES


def test_expiry_without_remnawave_uuid_still_expires(session_factory, monkeypatch):
    client = SimpleNamespace(disable_user=AsyncMock())
    _patch_remnawave(monkeypatch, client)

    async def scenario():
        user_id = await _add_subscription(session_factory, 1, None)
        await background.run_expiry_check_once(AsyncMock())
        assert await _sub_status(session_factory, user_id) == 'expired'

    asyncio.run(scenario())
    client.disable_user.assert_not_awaited()


def test_traffic_sync_aborts_after_consecutive_failures(session_factory, monkeypatch):
    client = SimpleNamespace(get_subscription_info=AsyncMock(side_effect=RuntimeError('panel down')))
    _patch_remnawave(monkeypatch, client)

    async def scenario():
        for telegram_id in range(1, 9):
            await _add_subscription(session_factory, telegram_id, f'uuid-{telegram_id}', expired=False)
        await background.run_traffic_sync_once()

    asyncio.run(scenario())
    assert client.get_subscription_info.await_count == background.REMNAWAVE_MAX_CONSECUTIVE_FAILURES


def test_traffic_sync_updates_usage(session_factory, monkeypatch):
    client = SimpleNamespace(get_subscription_info=AsyncMock(return_value=SimpleNamespace(traffic_used_gb=12.5)))
    _patch_remnawave(monkeypatch, client)

    async def scenario():
        user_id = await _add_subscription(session_factory, 1, 'uuid-1', expired=False)
        await background.run_traffic_sync_once()
        async with session_factory() as db:
            used = (await db.execute(select(Subscription.traffic_used_gb).where(Subscription.user_id == user_id))).scalar_one()
            assert used == 12.5

    asyncio.run(scenario())
