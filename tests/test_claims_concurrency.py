"""Гонки за слоты: лимит активаций промокода и одноразовый подарочный код.

Захват делается атомарным UPDATE ... WHERE, поэтому проверяется на SQLite так же,
как работает на Postgres (в отличие от SELECT ... FOR UPDATE, который SQLite
игнорирует). Подписка из тестов выдаётся через mock-Remnawave."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.database.models import GiftCode, PromoCode, PromoCodeUse, Subscription, User
from app.services import gift_service
from app.services.gift_service import GiftCodeError, redeem_gift_code
from app.services.promocode_service import PromoCodeError, activate_promocode
from tests.helpers import make_tariff, make_user

CONCURRENT_USERS = 8


# --- промокоды -----------------------------------------------------------------


async def _make_promo(factory, **fields) -> int:
    defaults = dict(code='SUMMER', type='balance', value=5000, max_activations=3)
    async with factory() as db:
        promo = PromoCode(**{**defaults, **fields})
        db.add(promo)
        await db.commit()
        return promo.id


async def _try_activate(factory, user_id: int, code: str = 'SUMMER') -> bool:
    """Ведёт себя как обработчик бота: ловит PromoCodeError и всё равно коммитит
    (AuthMiddleware коммитит сессию после хендлера)."""
    async with factory() as db:
        user = await db.get(User, user_id)
        try:
            await activate_promocode(db, code=code, user=user)
            ok = True
        except PromoCodeError:
            ok = False
        await db.commit()
        return ok


def test_promo_limit_holds_under_concurrent_activations(session_factory):
    async def scenario():
        user_ids = [await make_user(session_factory, telegram_id=i) for i in range(1, CONCURRENT_USERS + 1)]
        promo_id = await _make_promo(session_factory, max_activations=3)

        results = await asyncio.gather(*(_try_activate(session_factory, uid) for uid in user_ids))

        assert sum(results) == 3
        async with session_factory() as db:
            promo = await db.get(PromoCode, promo_id)
            assert promo.activations_count == 3
            assert await db.scalar(select(func.count()).select_from(PromoCodeUse)) == 3
            credited = await db.scalar(select(func.count()).select_from(User).where(User.balance_kopeks == 5000))
            assert credited == 3
            assert await db.scalar(select(func.sum(User.balance_kopeks))) == 3 * 5000

    asyncio.run(scenario())


def test_same_user_parallel_activation_counts_once(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        promo_id = await _make_promo(session_factory, max_activations=10)

        results = await asyncio.gather(*(_try_activate(session_factory, user_id) for _ in range(4)))

        assert sum(results) == 1
        async with session_factory() as db:
            assert (await db.get(User, user_id)).balance_kopeks == 5000
            assert (await db.get(PromoCode, promo_id)).activations_count == 1
            assert await db.scalar(select(func.count()).select_from(PromoCodeUse)) == 1

    asyncio.run(scenario())


def test_rejected_activation_changes_nothing_even_if_caller_commits(session_factory):
    """Лимит исчерпан -> PromoCodeError; счётчик и баланс не тронуты, хотя
    вызывающий код (бот) после ошибки всё равно коммитит сессию."""

    async def scenario():
        first = await make_user(session_factory, telegram_id=1)
        second = await make_user(session_factory, telegram_id=2, balance_kopeks=100)
        promo_id = await _make_promo(session_factory, max_activations=1)
        assert await _try_activate(session_factory, first) is True

        assert await _try_activate(session_factory, second) is False

        async with session_factory() as db:
            assert (await db.get(PromoCode, promo_id)).activations_count == 1
            assert (await db.get(User, second)).balance_kopeks == 100
            assert await db.scalar(select(func.count()).select_from(PromoCodeUse)) == 1

    asyncio.run(scenario())


def test_deactivated_promo_is_rejected(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        await _make_promo(session_factory, is_active=False)

        assert await _try_activate(session_factory, user_id) is False

    asyncio.run(scenario())


# --- подарочные коды -----------------------------------------------------------


async def _make_gift(factory, gifter_id: int, tariff_id: int, **fields) -> int:
    async with factory() as db:
        gift = GiftCode(
            code='GIFT123',
            tariff_id=tariff_id,
            period_days=30,
            gifter_user_id=gifter_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            **fields,
        )
        db.add(gift)
        await db.commit()
        return gift.id


async def _try_redeem(factory, user_id: int) -> bool:
    async with factory() as db:
        user = await db.get(User, user_id)
        try:
            await redeem_gift_code(db, code='GIFT123', recipient=user)
            ok = True
        except GiftCodeError:
            ok = False
        await db.commit()  # как AuthMiddleware после хендлера
        return ok


def test_gift_code_is_redeemed_once_under_concurrency(session_factory):
    async def scenario():
        gifter = await make_user(session_factory, telegram_id=100)
        tariff_id = await make_tariff(session_factory)
        gift_id = await _make_gift(session_factory, gifter, tariff_id)
        recipients = [await make_user(session_factory, telegram_id=i) for i in range(1, CONCURRENT_USERS + 1)]

        results = await asyncio.gather(*(_try_redeem(session_factory, uid) for uid in recipients))

        assert sum(results) == 1
        async with session_factory() as db:
            gift = await db.get(GiftCode, gift_id)
            winner = recipients[results.index(True)]
            assert gift.redeemed_by_user_id == winner and gift.redeemed_at is not None
            subs = (await db.execute(select(Subscription.user_id))).scalars().all()
            assert subs == [winner]

    asyncio.run(scenario())


def test_already_redeemed_gift_is_rejected_without_side_effects(session_factory):
    async def scenario():
        gifter = await make_user(session_factory, telegram_id=100)
        first = await make_user(session_factory, telegram_id=1)
        second = await make_user(session_factory, telegram_id=2)
        tariff_id = await make_tariff(session_factory)
        gift_id = await _make_gift(session_factory, gifter, tariff_id)
        assert await _try_redeem(session_factory, first) is True

        assert await _try_redeem(session_factory, second) is False

        async with session_factory() as db:
            assert (await db.get(GiftCode, gift_id)).redeemed_by_user_id == first
            assert await db.scalar(select(func.count()).select_from(Subscription)) == 1

    asyncio.run(scenario())


def test_failed_provisioning_releases_the_gift_code(session_factory, monkeypatch):
    """Remnawave упал после захвата кода: исключение без коммита откатывает захват,
    и код можно погасить повторно."""

    async def scenario():
        gifter = await make_user(session_factory, telegram_id=100)
        recipient = await make_user(session_factory, telegram_id=1)
        tariff_id = await make_tariff(session_factory)
        gift_id = await _make_gift(session_factory, gifter, tariff_id)

        original = gift_service.provision_or_extend_subscription

        async def boom(*args, **kwargs):
            raise RuntimeError('remnawave down')

        monkeypatch.setattr(gift_service, 'provision_or_extend_subscription', boom)
        async with session_factory() as db:
            user = await db.get(User, recipient)
            with pytest.raises(RuntimeError):
                await redeem_gift_code(db, code='GIFT123', recipient=user)
            await db.rollback()  # исключение не доходит до commit, как и в middleware

        async with session_factory() as db:
            assert (await db.get(GiftCode, gift_id)).redeemed_at is None

        monkeypatch.setattr(gift_service, 'provision_or_extend_subscription', original)
        assert await _try_redeem(session_factory, recipient) is True

    asyncio.run(scenario())


def test_expired_gift_is_rejected(session_factory):
    async def scenario():
        gifter = await make_user(session_factory, telegram_id=100)
        recipient = await make_user(session_factory, telegram_id=1)
        tariff_id = await make_tariff(session_factory)
        async with session_factory() as db:
            db.add(
                GiftCode(
                    code='GIFT123',
                    tariff_id=tariff_id,
                    period_days=30,
                    gifter_user_id=gifter,
                    expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                )
            )
            await db.commit()

        assert await _try_redeem(session_factory, recipient) is False

    asyncio.run(scenario())
