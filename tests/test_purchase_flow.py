"""handlers/subscription.py::purchase_or_renew_subscription — покупка и продление.

Платежи идут через stub-провайдер (мгновенный успех) либо через подменённого
"асинхронного" провайдера (pending -> подписку выдаёт finalize_pending_payment).
Remnawave — mock из conftest."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database.models import BotSetting, Payment, PromoGroup, Subscription, Tariff, Transaction, User
from app.handlers.subscription import purchase_or_renew_subscription
from app.services.balance_service import InsufficientBalanceError
from app.services.payment.base import CreatedPayment
from app.services.pricing_service import SALE_DISCOUNT_PERCENT_KEY, SALE_ENDS_AT_KEY
from tests.helpers import make_tariff, make_user

PRICE = 10000  # 100 ₽ за 30 дней


@pytest.fixture(autouse=True)
def stub_mode(monkeypatch):
    monkeypatch.setattr(settings, 'PAYMENTS_MODE', 'stub')
    monkeypatch.setattr(settings, 'REFERRAL_PERCENT', 25)


async def _tariff(factory, **fields) -> int:
    defaults = dict(name='Базовый', period_prices_kopeks={'30': PRICE, '90': 25000}, traffic_limit_gb=100, device_limit=3, squad_uuids=['s1'])
    return await make_tariff(factory, **{**defaults, **fields})


async def _buy(factory, user_id: int, tariff_id: int, *, period: int = 30, method: str = 'balance'):
    async with factory() as db:
        subscription = await purchase_or_renew_subscription(
            db, await db.get(User, user_id), await db.get(Tariff, tariff_id), period, method
        )
        await db.commit()
        return subscription.id if subscription else None


async def _state(factory, user_id: int):
    async with factory() as db:
        return SimpleNamespace(
            balance=(await db.get(User, user_id)).balance_kopeks,
            subscription=(await db.execute(select(Subscription).where(Subscription.user_id == user_id))).scalar_one_or_none(),
            payments=(await db.execute(select(Payment).where(Payment.user_id == user_id))).scalars().all(),
            transactions=(await db.execute(select(Transaction).where(Transaction.user_id == user_id))).scalars().all(),
        )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- оплата с баланса ----------------------------------------------------------


def test_first_purchase_from_balance(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=15000)
        tariff_id = await _tariff(session_factory)

        before = datetime.now(timezone.utc)
        await _buy(session_factory, user_id, tariff_id)

        state = await _state(session_factory, user_id)
        assert state.balance == 5000
        sub = state.subscription
        assert sub.status == 'active' and sub.is_trial is False and sub.tariff_id == tariff_id
        assert (sub.traffic_limit_gb, sub.device_limit) == (100, 3)
        assert timedelta(days=29, hours=23) < _aware(sub.end_date) - before < timedelta(days=30, hours=1)
        assert sub.subscription_url  # выдан доступ на панели
        (transaction,), (payment,) = state.transactions, state.payments
        assert (transaction.type, transaction.amount_kopeks, transaction.status) == ('subscription_payment', PRICE, 'completed')
        assert (payment.provider, payment.status, payment.amount_kopeks) == ('balance', 'success', PRICE)

    asyncio.run(scenario())


def test_insufficient_balance_leaves_no_traces(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=5000)
        tariff_id = await _tariff(session_factory)

        with pytest.raises(InsufficientBalanceError) as exc_info:
            await _buy(session_factory, user_id, tariff_id)

        assert exc_info.value.missing_kopeks == 5000
        state = await _state(session_factory, user_id)
        assert state.balance == 5000 and state.subscription is None
        assert state.payments == [] and state.transactions == []

    asyncio.run(scenario())


def test_period_without_price_is_rejected(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=99999)
        tariff_id = await _tariff(session_factory)

        with pytest.raises(ValueError):
            await _buy(session_factory, user_id, tariff_id, period=7)

        assert (await _state(session_factory, user_id)).balance == 99999

    asyncio.run(scenario())


def test_longer_period_uses_its_own_price(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=30000)
        tariff_id = await _tariff(session_factory)

        await _buy(session_factory, user_id, tariff_id, period=90)

        state = await _state(session_factory, user_id)
        assert state.balance == 5000  # 300 - 250 ₽
        assert _aware(state.subscription.end_date) - datetime.now(timezone.utc) > timedelta(days=89)

    asyncio.run(scenario())


# --- скидки --------------------------------------------------------------------


def test_promo_group_discount_is_charged(session_factory):
    async def scenario():
        async with session_factory() as db:
            group = PromoGroup(name='vip', discount_percent=20)
            db.add(group)
            await db.commit()
            group_id = group.id
        user_id = await make_user(session_factory, balance_kopeks=8000, promo_group_id=group_id)
        tariff_id = await _tariff(session_factory)

        await _buy(session_factory, user_id, tariff_id)

        state = await _state(session_factory, user_id)
        assert state.balance == 0  # заплатил 80 ₽ вместо 100
        assert state.transactions[0].amount_kopeks == 8000

    asyncio.run(scenario())


def test_discounted_price_is_still_enforced(session_factory):
    async def scenario():
        async with session_factory() as db:
            group = PromoGroup(name='vip', discount_percent=20)
            db.add(group)
            await db.commit()
            group_id = group.id
        user_id = await make_user(session_factory, balance_kopeks=7900, promo_group_id=group_id)
        tariff_id = await _tariff(session_factory)

        with pytest.raises(InsufficientBalanceError):
            await _buy(session_factory, user_id, tariff_id)

    asyncio.run(scenario())


def test_site_wide_sale_is_charged(session_factory):
    async def scenario():
        async with session_factory() as db:
            db.add(BotSetting(key=SALE_DISCOUNT_PERCENT_KEY, value='50'))
            db.add(BotSetting(key=SALE_ENDS_AT_KEY, value=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()))
            await db.commit()
        user_id = await make_user(session_factory, balance_kopeks=5000)
        tariff_id = await _tariff(session_factory)

        await _buy(session_factory, user_id, tariff_id)

        assert (await _state(session_factory, user_id)).balance == 0

    asyncio.run(scenario())


# --- продление -----------------------------------------------------------------


def test_renewal_of_active_subscription_extends_from_current_end(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=30000)
        tariff_id = await _tariff(session_factory)
        await _buy(session_factory, user_id, tariff_id)
        first_end = _aware((await _state(session_factory, user_id)).subscription.end_date)

        await _buy(session_factory, user_id, tariff_id)

        state = await _state(session_factory, user_id)
        assert _aware(state.subscription.end_date) - first_end == timedelta(days=30)  # оплаченные дни не теряются
        assert state.balance == 10000
        assert len(state.payments) == 2

    asyncio.run(scenario())


def test_renewal_of_expired_subscription_counts_from_now(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=30000)
        tariff_id = await _tariff(session_factory)
        await _buy(session_factory, user_id, tariff_id)
        async with session_factory() as db:
            sub = (await db.execute(select(Subscription))).scalar_one()
            sub.status, sub.end_date = 'expired', datetime.now(timezone.utc) - timedelta(days=5)
            await db.commit()

        await _buy(session_factory, user_id, tariff_id)

        sub = (await _state(session_factory, user_id)).subscription
        remaining = _aware(sub.end_date) - datetime.now(timezone.utc)
        assert sub.status == 'active'
        assert timedelta(days=29, hours=23) < remaining < timedelta(days=30, hours=1)  # без "дней в минус"

    asyncio.run(scenario())


def test_paying_converts_trial_and_resets_reminders(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=30000)
        tariff_id = await _tariff(session_factory)
        await _buy(session_factory, user_id, tariff_id)
        async with session_factory() as db:
            sub = (await db.execute(select(Subscription))).scalar_one()
            sub.is_trial, sub.reminder_3d_sent, sub.reminder_1d_sent = True, True, True
            await db.commit()

        await _buy(session_factory, user_id, tariff_id)

        sub = (await _state(session_factory, user_id)).subscription
        assert sub.is_trial is False and sub.reminder_3d_sent is False and sub.reminder_1d_sent is False

    asyncio.run(scenario())


def test_renewing_with_another_tariff_switches_limits(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=50000)
        basic = await _tariff(session_factory)
        family = await _tariff(session_factory, name='Семейный', traffic_limit_gb=0, device_limit=10, squad_uuids=['s2'])
        await _buy(session_factory, user_id, basic)

        await _buy(session_factory, user_id, family)

        sub = (await _state(session_factory, user_id)).subscription
        assert (sub.tariff_id, sub.device_limit, sub.traffic_limit_gb) == (family, 10, 0)

    asyncio.run(scenario())


def test_subscription_lost_on_panel_is_recreated_not_crashed(session_factory):
    """Пользователь в БД есть, а на панели его нет (потерян при миграции) — платящий
    клиент должен получить доступ, а не падение после списания денег."""

    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=30000)
        tariff_id = await _tariff(session_factory)
        await _buy(session_factory, user_id, tariff_id)
        async with session_factory() as db:
            (await db.get(User, user_id)).remnawave_uuid = None
            await db.commit()

        await _buy(session_factory, user_id, tariff_id)

        async with session_factory() as db:
            assert (await db.get(User, user_id)).remnawave_uuid is not None

    asyncio.run(scenario())


# --- оплата провайдером --------------------------------------------------------


def test_partial_balance_plus_provider(session_factory):
    """Баланс 30 ₽ гасит часть цены 100 ₽; провайдеру уходит остаток 70 ₽,
    рефереру комиссия считается с этих 70 ₽ (а не со 100)."""

    async def scenario():
        referrer_id = await make_user(session_factory, telegram_id=100, referral_commission_percent=10)
        user_id = await make_user(session_factory, telegram_id=200, balance_kopeks=3000, referred_by_id=referrer_id)
        tariff_id = await _tariff(session_factory)

        await _buy(session_factory, user_id, tariff_id, method='platega')

        state = await _state(session_factory, user_id)
        assert state.balance == 0
        (payment,), (transaction,) = state.payments, state.transactions
        assert payment.amount_kopeks == 7000 and transaction.amount_kopeks == PRICE
        assert payment.provider == 'cispay'  # реальный провайдер, а не витринный ключ 'platega'
        assert state.subscription is not None
        async with session_factory() as db:
            assert (await db.get(User, referrer_id)).balance_kopeks == 700  # 10% от 70 ₽

    asyncio.run(scenario())


def test_paying_from_balance_gives_referrer_nothing(session_factory):
    async def scenario():
        referrer_id = await make_user(session_factory, telegram_id=100)
        user_id = await make_user(session_factory, telegram_id=200, balance_kopeks=PRICE, referred_by_id=referrer_id)
        tariff_id = await _tariff(session_factory)

        await _buy(session_factory, user_id, tariff_id, method='balance')

        async with session_factory() as db:
            assert (await db.get(User, referrer_id)).balance_kopeks == 0

    asyncio.run(scenario())


def test_balance_fully_covering_price_skips_provider(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=20000)
        tariff_id = await _tariff(session_factory)

        await _buy(session_factory, user_id, tariff_id, method='platega')

        state = await _state(session_factory, user_id)
        assert state.balance == 10000
        assert state.payments[0].provider == 'balance'

    asyncio.run(scenario())


def test_async_provider_defers_everything_until_confirmed(session_factory, monkeypatch):
    """Провайдер вернул pending: подписку не выдаём и баланс не трогаем — всё это
    сделает finalize_pending_payment после подтверждения оплаты."""

    class AsyncProvider:
        async def create_payment(self, **kwargs) -> CreatedPayment:
            return CreatedPayment(external_id='ext-42', payment_url='https://pay.example/42', status='pending')

    monkeypatch.setattr('app.services.payment.router.get_payment_provider', lambda name: AsyncProvider())

    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=3000)
        tariff_id = await _tariff(session_factory)

        result = await _buy(session_factory, user_id, tariff_id, method='platega')

        assert result is None
        state = await _state(session_factory, user_id)
        assert state.balance == 3000 and state.subscription is None
        (payment,), (transaction,) = state.payments, state.transactions
        assert (payment.status, payment.provider, payment.external_id) == ('pending', 'cispay', 'ext-42')
        assert payment.amount_kopeks == 7000 and transaction.status == 'pending'
        assert payment.raw_payload == {
            'kind': 'subscription',
            'tariff_id': tariff_id,
            'period_days': 30,
            'payment_url': 'https://pay.example/42',
            'balance_offset_kopeks': 3000,
        }

    asyncio.run(scenario())
