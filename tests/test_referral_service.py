"""app/services/referral_service.py — реферальная комиссия и бонус за приглашение.

Комиссия = процент от РЕАЛЬНО оплаченной провайдеру суммы (payment.amount_kopeks),
округление вверх до целого рубля (в пользу реферера). С оплаты собственным
балансом, с неуспешных платежей и заблокированному рефереру не платится."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database.models import Payment, ReferralEarning, Subscription, Transaction, User
from app.services.referral_service import REFERRAL_INVITE_BONUS_DAYS, credit_referral_earning, credit_referral_invite_bonus
from tests.helpers import make_tariff, make_user


@pytest.fixture(autouse=True)
def default_percent(monkeypatch):
    monkeypatch.setattr(settings, 'REFERRAL_PERCENT', 25)


async def _payment(factory, buyer_id: int, *, amount=10000, provider='cispay', status='success', tx_type='subscription_payment') -> int:
    async with factory() as db:
        transaction = Transaction(user_id=buyer_id, type=tx_type, amount_kopeks=amount, status='completed')
        db.add(transaction)
        await db.flush()
        payment = Payment(
            user_id=buyer_id, transaction_id=transaction.id, provider=provider, external_id=f'ext-{buyer_id}-{amount}-{provider}-{status}',
            amount_kopeks=amount, status=status,
        )
        db.add(payment)
        await db.commit()
        return payment.id


async def _credit(factory, payment_id: int, bot=None) -> None:
    async with factory() as db:
        await credit_referral_earning(db, await db.get(Payment, payment_id), bot=bot)
        await db.commit()


async def _pair(factory, **referrer_fields) -> tuple[int, int]:
    referrer_id = await make_user(factory, telegram_id=100, **referrer_fields)
    buyer_id = await make_user(factory, telegram_id=200, referred_by_id=referrer_id)
    return referrer_id, buyer_id


async def _referrer_state(factory, referrer_id: int):
    async with factory() as db:
        balance = (await db.get(User, referrer_id)).balance_kopeks
        earnings = (await db.execute(select(ReferralEarning))).scalars().all()
        rewards = (await db.execute(select(Transaction).where(Transaction.type == 'referral_reward'))).scalars().all()
        return balance, earnings, rewards


def test_default_percent_credits_referrer_and_records_everything(session_factory):
    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory)
        payment_id = await _payment(session_factory, buyer_id, amount=10000)
        bot = AsyncMock()

        await _credit(session_factory, payment_id, bot=bot)

        balance, (earning,), (reward,) = await _referrer_state(session_factory, referrer_id)
        assert balance == 2500  # 25% от 100 ₽
        assert (earning.user_id, earning.source_user_id, earning.payment_id) == (referrer_id, buyer_id, payment_id)
        assert (earning.amount_kopeks, earning.source) == (2500, 'purchase')
        assert (reward.user_id, reward.amount_kopeks, reward.status) == (referrer_id, 2500, 'completed')
        bot.send_message.assert_awaited_once()
        assert bot.send_message.await_args.kwargs['chat_id'] == 100

    asyncio.run(scenario())


@pytest.mark.parametrize(
    'amount, expected',
    [(9999, 2500), (10100, 2600), (10400, 2600), (10401, 2700), (100, 100)],  # вверх до целого рубля
)
def test_commission_is_rounded_up_to_whole_rubles(session_factory, amount, expected):
    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory)
        await _credit(session_factory, await _payment(session_factory, buyer_id, amount=amount))
        balance, _, _ = await _referrer_state(session_factory, referrer_id)
        assert balance == expected
        assert balance % 100 == 0

    asyncio.run(scenario())


def test_personal_percent_overrides_default(session_factory):
    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory, referral_commission_percent=10)
        await _credit(session_factory, await _payment(session_factory, buyer_id, amount=10000))

        assert (await _referrer_state(session_factory, referrer_id))[0] == 1000

    asyncio.run(scenario())


def test_personal_zero_percent_disables_commission(session_factory):
    """0 — это "не платить", а не "взять глобальный" (глобальный — только NULL)."""

    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory, referral_commission_percent=0)
        await _credit(session_factory, await _payment(session_factory, buyer_id))

        balance, earnings, rewards = await _referrer_state(session_factory, referrer_id)
        assert balance == 0 and earnings == [] and rewards == []

    asyncio.run(scenario())


def test_topup_payment_is_recorded_as_topup_source(session_factory):
    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory)
        await _credit(session_factory, await _payment(session_factory, buyer_id, tx_type='topup'))

        _, (earning,), _ = await _referrer_state(session_factory, referrer_id)
        assert earning.source == 'topup'

    asyncio.run(scenario())


@pytest.mark.parametrize(
    'payment_fields',
    [
        dict(provider='balance'),  # оплата своим балансом — новых денег нет
        dict(status='pending'),
        dict(status='failed'),
        dict(amount=0),
    ],
    ids=['paid_from_balance', 'pending', 'failed', 'zero_amount'],
)
def test_no_commission_for_ineligible_payments(session_factory, payment_fields):
    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory)
        await _credit(session_factory, await _payment(session_factory, buyer_id, **payment_fields))

        balance, earnings, rewards = await _referrer_state(session_factory, referrer_id)
        assert balance == 0 and earnings == [] and rewards == []

    asyncio.run(scenario())


def test_no_commission_without_referrer(session_factory):
    async def scenario():
        buyer_id = await make_user(session_factory, telegram_id=200)
        await _credit(session_factory, await _payment(session_factory, buyer_id))

        async with session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(ReferralEarning)) == 0

    asyncio.run(scenario())


def test_blocked_referrer_gets_nothing(session_factory):
    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory, is_blocked=True)
        await _credit(session_factory, await _payment(session_factory, buyer_id))

        balance, earnings, _ = await _referrer_state(session_factory, referrer_id)
        assert balance == 0 and earnings == []

    asyncio.run(scenario())


def test_failed_notification_does_not_cancel_the_commission(session_factory):
    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory)
        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError('telegram down')

        await _credit(session_factory, await _payment(session_factory, buyer_id), bot=bot)

        assert (await _referrer_state(session_factory, referrer_id))[0] == 2500

    asyncio.run(scenario())


def test_repeated_call_for_same_payment_does_not_double_pay(session_factory):
    """Идемпотентность: повтор для того же платежа не начисляет, не дублирует
    запись/транзакцию и не шлёт второе уведомление."""

    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory)
        payment_id = await _payment(session_factory, buyer_id)
        bot = AsyncMock()

        await _credit(session_factory, payment_id, bot=bot)
        await _credit(session_factory, payment_id, bot=bot)
        await _credit(session_factory, payment_id, bot=bot)

        balance, earnings, rewards = await _referrer_state(session_factory, referrer_id)
        assert balance == 2500 and len(earnings) == 1 and len(rewards) == 1
        assert bot.send_message.await_count == 1

    asyncio.run(scenario())


def test_each_new_payment_of_the_same_buyer_is_paid_separately(session_factory):
    """Защита от дублей — по платежу, а не по покупателю: каждая новая оплата
    приносит комиссию."""

    async def scenario():
        referrer_id, buyer_id = await _pair(session_factory)
        first = await _payment(session_factory, buyer_id, amount=10000)
        second = await _payment(session_factory, buyer_id, amount=20000)

        await _credit(session_factory, first)
        await _credit(session_factory, second)
        await _credit(session_factory, first)  # повтор старого — без эффекта

        balance, earnings, _ = await _referrer_state(session_factory, referrer_id)
        assert balance == 2500 + 5000 and len(earnings) == 2

    asyncio.run(scenario())


# --- бонус за приглашение ------------------------------------------------------


def test_invite_bonus_grants_days_to_referrer(session_factory):
    async def scenario():
        referrer_id = await make_user(session_factory, telegram_id=100)
        await make_tariff(session_factory)
        async with session_factory() as db:
            await credit_referral_invite_bonus(db, await db.get(User, referrer_id))
            await db.commit()

        async with session_factory() as db:
            sub = (await db.execute(select(Subscription).where(Subscription.user_id == referrer_id))).scalar_one()
            assert sub.status == 'active'
            assert REFERRAL_INVITE_BONUS_DAYS == 3

    asyncio.run(scenario())


def test_invite_bonus_extends_existing_subscription(session_factory):
    async def scenario():
        referrer_id = await make_user(session_factory, telegram_id=100)
        await make_tariff(session_factory)
        for _ in range(2):
            async with session_factory() as db:
                await credit_referral_invite_bonus(db, await db.get(User, referrer_id))
                await db.commit()

        async with session_factory() as db:
            subs = (await db.execute(select(Subscription).where(Subscription.user_id == referrer_id))).scalars().all()
            assert len(subs) == 1  # продлили, а не завели вторую

    asyncio.run(scenario())


def test_invite_bonus_skipped_for_blocked_referrer(session_factory):
    async def scenario():
        referrer_id = await make_user(session_factory, telegram_id=100, is_blocked=True)
        await make_tariff(session_factory)
        async with session_factory() as db:
            await credit_referral_invite_bonus(db, await db.get(User, referrer_id))
            await db.commit()

        async with session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(Subscription)) == 0

    asyncio.run(scenario())


def test_invite_bonus_without_active_tariff_does_not_raise(session_factory):
    async def scenario():
        referrer_id = await make_user(session_factory, telegram_id=100)
        async with session_factory() as db:
            await credit_referral_invite_bonus(db, await db.get(User, referrer_id))  # не должно бросать

    asyncio.run(scenario())
