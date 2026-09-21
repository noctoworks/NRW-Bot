"""notify_* используют правки владельца: свой текст, выключение, откат на заводской текст, кнопки."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.config import settings
from app.database.models import MessageTemplate
from app.services import notification_service as ns
from app.services.message_templates import service
from app.services.message_templates.service import invalidate_cache

CHAT = 42


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(service, 'AsyncSessionLocal', session_factory)
    invalidate_cache()
    yield
    invalidate_cache()


async def _set(factory, key: str, **fields) -> None:
    async with factory() as db:
        db.add(MessageTemplate(key=key, **fields))
        await db.commit()
    invalidate_cache()


def test_custom_payment_text_is_used_and_values_are_escaped(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'payment_success', template='🧾 {amount}₽ — <b>{description}</b>')
        await ns.notify_payment_success(bot, telegram_id=CHAT, amount_kopeks=24900, description='Тариф <VIP> & Co')

    asyncio.run(scenario())

    assert bot.send_message.await_args.kwargs['text'] == '🧾 249.00₽ — <b>Тариф &lt;VIP&gt; &amp; Co</b>'


def test_balance_change_picks_credit_or_debit_template(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'balance_credited', template='+{amount} (итого {balance})')
        await _set(session_factory, 'balance_debited', template='-{amount} (итого {balance})')
        await ns.notify_balance_changed(bot, telegram_id=CHAT, amount_kopeks=10000, new_balance_kopeks=35000)
        await ns.notify_balance_changed(bot, telegram_id=CHAT, amount_kopeks=-5000, new_balance_kopeks=30000)

    asyncio.run(scenario())

    assert [call.kwargs['text'] for call in bot.send_message.await_args_list] == ['+100.00 (итого 350.00)', '-50.00 (итого 300.00)']


def test_gift_redeemed_variable_who(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'gift_redeemed', template='🎁 {who} принял подарок')
        await ns.notify_gift_redeemed_to_gifter(bot, gifter_telegram_id=CHAT, recipient_username=None)
        await ns.notify_gift_redeemed_to_gifter(bot, gifter_telegram_id=CHAT, recipient_username='friend')

    asyncio.run(scenario())

    assert [call.kwargs['text'] for call in bot.send_message.await_args_list] == ['🎁 пользователь принял подарок', '🎁 @friend принял подарок']


def test_disabled_event_is_not_sent(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'subscription_expiring', enabled=False)
        await ns.notify_subscription_expiring(bot, telegram_id=CHAT, days_left=3)

    asyncio.run(scenario())

    bot.send_message.assert_not_awaited()


def test_broken_template_falls_back_to_the_legacy_text(session_factory):
    bot = AsyncMock()
    bot.send_message.side_effect = [TelegramBadRequest(method=SendMessage(chat_id=CHAT, text='x'), message="can't parse entities"), None]

    async def scenario():
        await _set(session_factory, 'subscription_expired', template='<b>без закрытия')
        await ns.notify_subscription_expired(bot, telegram_id=CHAT)

    asyncio.run(scenario())

    assert bot.send_message.await_args.kwargs['text'] == '❌ Ваша подписка истекла. Продлите её в главном меню.'


def test_button_events_use_custom_label_but_keep_the_action(session_factory, monkeypatch):
    monkeypatch.setattr(settings, 'MINIAPP_URL', '')
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'welcome_nudge', button_text='Погнали', template='Привет, друг')
        await ns.notify_welcome_nudge(bot, telegram_id=CHAT)

    asyncio.run(scenario())

    button = bot.send_message.await_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert (button.text, button.callback_data) == ('Погнали', 'sub:buy')
    assert bot.send_message.await_args.kwargs['text'] == 'Привет, друг'


def test_database_failure_still_sends_default_text(monkeypatch):
    monkeypatch.setattr(service, 'AsyncSessionLocal', lambda: (_ for _ in ()).throw(RuntimeError('db down')))
    bot = AsyncMock()

    asyncio.run(ns.notify_autopay_activated(bot, telegram_id=CHAT))

    assert bot.send_message.await_args.kwargs['text'].startswith('🔄 Автоплатёж подключён')
