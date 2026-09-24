"""Сообщения о скидке триальным пользователям: тексты trial_ending / trial_expired, дедлайн в МСК и выбор
между «триальным» и обычным сообщением в фоновой проверке истечения (run_expiry_check_once)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.database.models import Subscription
from app.keyboards.main_menu import CB_SUBSCRIPTION_RENEW
from app.services import background
from app.services import notification_service as ns
from app.services.message_templates.registry import get_event
from app.services.pricing_service import TRIAL_WINBACK_DISCOUNT_PERCENT
from tests.helpers import make_tariff, make_user

CHAT = 42
DEADLINE = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)  # 15:00 по Москве


def _sent(bot) -> tuple[str, object]:
    kwargs = bot.send_message.await_args.kwargs
    return kwargs['text'], kwargs.get('reply_markup')


def test_trial_events_are_registered_with_discount_variables_and_a_button():
    for key in ('trial_ending', 'trial_expired'):
        event = get_event(key)
        assert event.group == 'Подписка'
        assert set(event.variable_names) == {'discount_percent', 'until'}
        assert event.has_button and event.button_label(True) == event.button_label(False) == '💎 Подключиться со скидкой'


def test_trial_ending_message_names_percent_and_deadline_in_moscow_time_and_offers_a_button():
    bot = AsyncMock()

    asyncio.run(ns.notify_trial_ending(bot, telegram_id=CHAT, discount_percent=20, deadline=DEADLINE))

    text, markup = _sent(bot)
    assert text == '⏳ Пробный период заканчивается завтра. Оформите подписку со скидкой 20% — предложение действует до 27.09 в 15:00 МСК.'
    [[button]] = markup.inline_keyboard
    assert button.text == '💎 Подключиться со скидкой'
    assert button.callback_data == CB_SUBSCRIPTION_RENEW  # без MINIAPP_URL — прежний чат-сценарий оплаты


def test_trial_expired_message_names_percent_and_deadline():
    bot = AsyncMock()

    asyncio.run(ns.notify_trial_expired(bot, telegram_id=CHAT, discount_percent=20, deadline=DEADLINE))

    text, markup = _sent(bot)
    assert text == '⌛ Пробный период закончился. Скидка 20% на первую подписку ещё действует — до 27.09 в 15:00 МСК.'
    assert markup is not None


def test_deadline_near_midnight_rolls_over_to_the_next_moscow_day():
    bot = AsyncMock()
    late_utc = datetime(2026, 9, 27, 22, 30, tzinfo=timezone.utc)  # 01:30 28.09 по Москве

    asyncio.run(ns.notify_trial_ending(bot, telegram_id=CHAT, discount_percent=20, deadline=late_utc))

    assert 'до 28.09 в 01:30 МСК' in _sent(bot)[0]


# --- фоновая проверка истечения ------------------------------------------------------------------------------------


async def _subscription(factory, *, is_trial: bool, ends_in: timedelta, status: str = 'active', telegram_id: int = 1) -> int:
    user_id = await make_user(factory, telegram_id=telegram_id)
    tariff_id = await make_tariff(factory, name=f'T{telegram_id}')
    async with factory() as db:
        db.add(Subscription(
            user_id=user_id, tariff_id=tariff_id, status=status, is_trial=is_trial,
            end_date=datetime.now(timezone.utc) + ends_in,
        ))
        await db.commit()
    return user_id


@pytest.fixture(autouse=True)
def isolated_background(monkeypatch, session_factory):
    monkeypatch.setattr(background, 'AsyncSessionLocal', session_factory)
    monkeypatch.setattr(background, 'get_remnawave_client', lambda: SimpleNamespace(disable_user=AsyncMock()))


def _run(session_factory, **subscription) -> str:
    bot = AsyncMock()

    async def scenario():
        await _subscription(session_factory, **subscription)
        await background.run_expiry_check_once(bot)

    asyncio.run(scenario())
    return _sent(bot)[0]


def test_one_day_reminder_for_a_trial_user_mentions_the_discount(session_factory):
    text = _run(session_factory, is_trial=True, ends_in=timedelta(hours=12))

    assert f'скидкой {TRIAL_WINBACK_DISCOUNT_PERCENT}%' in text and 'Пробный период' in text


def test_one_day_reminder_for_a_paying_user_stays_the_regular_one(session_factory):
    text = _run(session_factory, is_trial=False, ends_in=timedelta(hours=12))

    assert text == '⏳ Ваша подписка истекает через 1 дн.'


def test_expiry_notice_for_a_trial_user_mentions_the_discount(session_factory):
    text = _run(session_factory, is_trial=True, ends_in=-timedelta(hours=1))

    assert 'Пробный период закончился' in text and f'Скидка {TRIAL_WINBACK_DISCOUNT_PERCENT}%' in text


def test_expiry_notice_for_a_paying_user_stays_the_regular_one(session_factory):
    text = _run(session_factory, is_trial=False, ends_in=-timedelta(hours=1))

    assert text == '❌ Ваша подписка истекла. Продлите её в главном меню.'


def test_trial_expiry_processed_after_the_window_closed_gets_the_regular_notice(session_factory):
    """Если проверка истечения долго не работала и окно скидки уже закрылось — обещать скидку нельзя."""
    text = _run(session_factory, is_trial=True, ends_in=-timedelta(days=4))

    assert text == '❌ Ваша подписка истекла. Продлите её в главном меню.'
