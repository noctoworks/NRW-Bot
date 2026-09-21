"""Тесты app/services/payment_finalization.py на SQLite.

Не покрыто: реальная гонка вебхука и поллинга за один платёж — защита там
держится на SELECT ... FOR UPDATE (SQLite его игнорирует), поэтому проверяется
идемпотентность повторного вызова, а не параллельная блокировка."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.database.models import GiftCode, Payment, ReferralEarning, Subscription, Transaction, User
from app.services import payment_finalization
from app.services.payment_finalization import finalize_pending_payment, mark_payment_failed
from tests.helpers import make_tariff, make_user


async def _make_pending_payment(factory, user_id: int, raw_payload: dict, amount: int = 10000) -> int:
    async with factory() as db:
        transaction = Transaction(user_id=user_id, type='subscription_payment', amount_kopeks=amount, status='pending')
        db.add(transaction)
        await db.flush()
        payment = Payment(
            user_id=user_id,
            transaction_id=transaction.id,
            provider='cispay',
            external_id='ext-1',
            amount_kopeks=amount,
            status='pending',
            raw_payload=raw_payload,
        )
        db.add(payment)
        await db.commit()
        return payment.id


async def _finalize(factory, payment_id: int) -> None:
    async with factory() as db:
        payment = await db.get(Payment, payment_id)
        await finalize_pending_payment(db, payment, AsyncMock())


def _subscription_payload(tariff_id: int, **extra) -> dict:
    return {'kind': 'subscription', 'tariff_id': tariff_id, 'period_days': 30, **extra}


def test_subscription_payment_is_finalized(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        payment_id = await _make_pending_payment(session_factory, user_id, _subscription_payload(tariff_id))

        await _finalize(session_factory, payment_id)

        async with session_factory() as db:
            payment = await db.get(Payment, payment_id)
            assert payment.status == 'success'
            assert (await db.get(Transaction, payment.transaction_id)).status == 'completed'
            sub = (await db.execute(select(Subscription).where(Subscription.user_id == user_id))).scalar_one()
            assert sub.tariff_id == tariff_id and sub.is_trial is False

    asyncio.run(scenario())


def test_second_finalize_is_idempotent(session_factory):
    """Вебхук и поллинг приходят на один платёж — вторая обработка не должна
    ни продлевать подписку повторно, ни начислять реферальную комиссию дважды."""

    async def scenario():
        referrer_id = await make_user(session_factory, telegram_id=10, referral_commission_percent=10)
        buyer_id = await make_user(session_factory, telegram_id=11, referred_by_id=referrer_id)
        tariff_id = await make_tariff(session_factory)
        payment_id = await _make_pending_payment(session_factory, buyer_id, _subscription_payload(tariff_id))

        await _finalize(session_factory, payment_id)
        async with session_factory() as db:
            first_end = (await db.execute(select(Subscription.end_date))).scalar_one()

        await _finalize(session_factory, payment_id)

        async with session_factory() as db:
            assert (await db.execute(select(Subscription.end_date))).scalar_one() == first_end
            assert await db.scalar(select(func.count()).select_from(ReferralEarning)) == 1
            assert (await db.get(User, referrer_id)).balance_kopeks == 1000  # 10% от 100 ₽

    asyncio.run(scenario())


def test_balance_offset_is_debited_on_finalize(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=3000)
        tariff_id = await make_tariff(session_factory)
        payment_id = await _make_pending_payment(
            session_factory, user_id, _subscription_payload(tariff_id, balance_offset_kopeks=2000), amount=8000
        )

        await _finalize(session_factory, payment_id)

        async with session_factory() as db:
            assert (await db.get(User, user_id)).balance_kopeks == 1000

    asyncio.run(scenario())


def test_balance_offset_never_drives_balance_negative(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=500)
        tariff_id = await make_tariff(session_factory)
        payment_id = await _make_pending_payment(
            session_factory, user_id, _subscription_payload(tariff_id, balance_offset_kopeks=2000), amount=8000
        )

        await _finalize(session_factory, payment_id)

        async with session_factory() as db:
            assert (await db.get(User, user_id)).balance_kopeks == 0
            assert (await db.get(Payment, payment_id)).status == 'success'

    asyncio.run(scenario())


def test_gift_payment_creates_gift_code_not_subscription(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        payment_id = await _make_pending_payment(
            session_factory, user_id, {'kind': 'gift', 'tariff_id': tariff_id, 'period_days': 30}
        )

        await _finalize(session_factory, payment_id)

        async with session_factory() as db:
            assert (await db.get(Payment, payment_id)).status == 'success'
            gift = (await db.execute(select(GiftCode))).scalar_one()
            assert gift.gifter_user_id == user_id and gift.period_days == 30
            assert await db.scalar(select(func.count()).select_from(Subscription)) == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    'payload',
    [
        {'kind': 'subscription', 'period_days': 30},
        {'kind': 'unknown', 'tariff_id': 1, 'period_days': 30},
        {'kind': 'subscription', 'tariff_id': 999, 'period_days': 30},
        {},
    ],
    ids=['no_tariff_id', 'unknown_kind', 'missing_tariff', 'empty'],
)
def test_incomplete_payload_leaves_payment_pending(session_factory, payload):
    async def scenario():
        user_id = await make_user(session_factory)
        await make_tariff(session_factory)
        payment_id = await _make_pending_payment(session_factory, user_id, payload)

        await _finalize(session_factory, payment_id)

        async with session_factory() as db:
            assert (await db.get(Payment, payment_id)).status == 'pending'
            assert await db.scalar(select(func.count()).select_from(Subscription)) == 0

    asyncio.run(scenario())


def test_provisioning_failure_keeps_payment_pending(session_factory, monkeypatch):
    """Если Remnawave упал — платёж не должен стать success без выданной подписки."""

    async def boom(*args, **kwargs):
        raise RuntimeError('remnawave down')

    monkeypatch.setattr(payment_finalization, 'provision_or_extend_subscription', boom)

    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=3000)
        tariff_id = await make_tariff(session_factory)
        payment_id = await _make_pending_payment(
            session_factory, user_id, _subscription_payload(tariff_id, balance_offset_kopeks=2000)
        )

        async with session_factory() as db:
            payment = await db.get(Payment, payment_id)
            with pytest.raises(RuntimeError):
                await finalize_pending_payment(db, payment, AsyncMock())
            await db.rollback()

        async with session_factory() as db:
            assert (await db.get(Payment, payment_id)).status == 'pending'
            assert (await db.get(User, user_id)).balance_kopeks == 3000

    asyncio.run(scenario())


def test_mark_payment_failed(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        payment_id = await _make_pending_payment(session_factory, user_id, {})

        async with session_factory() as db:
            await mark_payment_failed(db, await db.get(Payment, payment_id))

        async with session_factory() as db:
            payment = await db.get(Payment, payment_id)
            assert payment.status == 'failed'
            assert (await db.get(Transaction, payment.transaction_id)).status == 'failed'

    asyncio.run(scenario())


def test_mark_failed_does_not_override_success(session_factory):
    """Поздний 'failed'-колбэк не должен откатывать уже подтверждённый платёж."""

    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        payment_id = await _make_pending_payment(session_factory, user_id, _subscription_payload(tariff_id))
        await _finalize(session_factory, payment_id)

        async with session_factory() as db:
            await mark_payment_failed(db, await db.get(Payment, payment_id))

        async with session_factory() as db:
            payment = await db.get(Payment, payment_id)
            assert payment.status == 'success'
            assert (await db.get(Transaction, payment.transaction_id)).status == 'completed'

    asyncio.run(scenario())
