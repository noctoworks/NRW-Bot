"""Редактор шаблонов сообщений в админке бота (обработчики вызываются напрямую)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, MessageEntity

from app.database.models import MessageTemplate, User
from app.handlers import message_templates_admin as h
from app.handlers import register_all_handlers
from app.handlers.admin import _root_keyboard
from app.services.message_templates import service
from app.services.message_templates.registry import EVENTS
from app.services.message_templates.service import get_overrides, invalidate_cache
from app.states import AdminTemplateStates
from tests.helpers import make_user

ADMIN_TG = 555


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(service, 'AsyncSessionLocal', session_factory)
    invalidate_cache()
    yield
    invalidate_cache()


def _state() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=ADMIN_TG, user_id=ADMIN_TG))


def _callback(data: str):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=ADMIN_TG),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
        bot=AsyncMock(),
    )


def _message(html_text: str):
    return SimpleNamespace(html_text=html_text, text=html_text, answer=AsyncMock())


def _admin(admin_id: int) -> User:
    return User(id=admin_id, telegram_id=ADMIN_TG, referral_code='a', is_admin=True)


def _shown(callback) -> tuple[str, object]:
    """(текст, клавиатура) последнего показанного экрана (edit_text либо answer)."""
    for method in (callback.message.edit_text, callback.message.answer):
        if method.await_args is not None:
            args, kwargs = method.await_args
            return args[0], kwargs.get('reply_markup')
    raise AssertionError('экран не показан')


def _buttons(markup) -> list:
    return [button for row in markup.inline_keyboard for button in row]


async def _run(session_factory, handler, *args, commit: bool = True):
    """Вызывает обработчик в своей сессии и коммитит её — как AuthMiddleware после хендлера."""
    async with session_factory() as db:
        result = await handler(*[db if arg is None else arg for arg in args])
        if commit:
            await db.commit()
        return result


def test_root_button_exists_in_admin_menu_and_router_is_registered():
    callbacks = [button.callback_data for button in _buttons(_root_keyboard())]
    dispatcher = Dispatcher()
    register_all_handlers(dispatcher)

    assert h.CB_ROOT in callbacks
    assert 'message_templates_admin' in [router.name for router in dispatcher.sub_routers]


def test_non_admin_is_ignored(session_factory):
    async def scenario():
        callback = _callback(h.CB_ROOT)
        stranger = User(id=9, telegram_id=1, referral_code='x', is_admin=False)

        await _run(session_factory, h.cb_root, callback, None, stranger, _state())

        callback.message.edit_text.assert_not_awaited()
        callback.message.answer.assert_not_awaited()

    asyncio.run(scenario())


def test_root_lists_all_events_with_marks(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            db.add(MessageTemplate(key='winback', template='Свой', enabled=False))
            await db.commit()
        callback = _callback(h.CB_ROOT)

        await _run(session_factory, h.cb_root, callback, None, _admin(admin), _state())

        buttons = _buttons(_shown(callback)[1])
        event_buttons = [b for b in buttons if b.callback_data.startswith(h.CB_CARD)]
        assert [b.callback_data[len(h.CB_CARD):] for b in event_buttons] == [e.key for e in EVENTS]
        winback = next(b for b in event_buttons if b.callback_data.endswith('winback'))
        assert '🚫' in winback.text and '✏️' in winback.text
        plain = next(b for b in event_buttons if b.callback_data.endswith('payment_success'))
        assert plain.text.startswith('✅') and '✏️' not in plain.text
        assert buttons[-1].callback_data == 'admin:root' or buttons[-1].callback_data.startswith('admin:')  # «Назад»

    asyncio.run(scenario())


def test_card_shows_trigger_variables_and_current_text(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        callback = _callback(f'{h.CB_CARD}payment_success')

        await _run(session_factory, h.cb_card, callback, None, _admin(admin), _state())

        text, markup = _shown(callback)
        assert 'Оплата прошла' in text and 'Платёж подтверждён' in text
        assert '{amount}' in text and '{description}' in text
        assert '✅ Оплата на сумму 249.00₽ прошла успешно.' in text  # предпросмотр с примерами
        labels = [b.text for b in _buttons(markup)]
        assert any('Изменить текст' in label for label in labels) and not any('Текст кнопки' in label for label in labels)
        assert any('Тест' in label for label in labels)

    asyncio.run(scenario())


def test_card_of_button_event_offers_button_editing(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        callback = _callback(f'{h.CB_CARD}winback')

        await _run(session_factory, h.cb_card, callback, None, _admin(admin), _state())

        assert any('Текст кнопки' in b.text for b in _buttons(_shown(callback)[1]))

    asyncio.run(scenario())


def test_edit_flow_saves_after_confirmation_and_shows_fresh_state(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await h.cb_edit(_callback(f'{h.CB_EDIT}payment_success'), _admin(admin), state)
        assert await state.get_state() == AdminTemplateStates.entering_text.state

        message = _message('🧾 <b>{amount}₽</b> — {description}')
        await _run(session_factory, h.on_template_text, message, None, _admin(admin), state)
        assert await state.get_state() == AdminTemplateStates.confirming.state
        assert '249.00' in message.answer.await_args.args[0]  # предпросмотр
        assert await get_overrides() == {}  # до подтверждения ничего не сохранено

        callback = _callback(h.CB_SAVE)
        async with session_factory() as db:
            await h.cb_save(callback, db, _admin(admin), state)
            # ещё ДО коммита экран уже показывает свежее состояние (читает сессию обработчика)
            assert 'текст изменён' in _shown(callback)[0]
            assert await get_overrides() == {}  # другие читатели до коммита видят старое
            await db.commit()

        assert await state.get_state() is None
        assert (await get_overrides())['payment_success'].template == '🧾 <b>{amount}₽</b> — {description}'

    asyncio.run(scenario())


def test_invalid_text_is_rejected_with_reasons_and_state_is_kept(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await h.cb_edit(_callback(f'{h.CB_EDIT}payment_success'), _admin(admin), state)

        message = _message('<b>не закрыт {nope}')
        await _run(session_factory, h.on_template_text, message, None, _admin(admin), state)

        reply = message.answer.await_args.args[0]
        assert '{nope}' in reply and 'Не закрыты' in reply
        assert await state.get_state() == AdminTemplateStates.entering_text.state
        assert await get_overrides() == {}

    asyncio.run(scenario())


def test_custom_emoji_message_is_converted_to_tg_emoji_markup(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        real = Message(
            message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=ADMIN_TG, type='private'),
            text='🏦 Подписка закончилась',
            entities=[MessageEntity(type='custom_emoji', offset=0, length=2, custom_emoji_id='5368446439800197476')],
        )
        state = _state()
        await h.cb_edit(_callback(f'{h.CB_EDIT}subscription_expired'), _admin(admin), state)
        message = _message(real.html_text)  # то, что aiogram отдаёт из настоящего сообщения
        await _run(session_factory, h.on_template_text, message, None, _admin(admin), state)
        await _run(session_factory, h.cb_save, _callback(h.CB_SAVE), None, _admin(admin), state)

        saved = (await get_overrides())['subscription_expired'].template
        assert saved == '<tg-emoji emoji-id="5368446439800197476">🏦</tg-emoji> Подписка закончилась'
        reply = message.answer.await_args.args[0]
        assert 'Тест' in reply  # предупреждение про проверку эмодзи
        assert '<tg-emoji' not in reply  # в предпросмотре — только символ

    asyncio.run(scenario())


def test_cancel_discards_pending_text(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await h.cb_edit(_callback(f'{h.CB_EDIT}subscription_expired'), _admin(admin), state)
        await _run(session_factory, h.on_template_text, _message('Новый текст'), None, _admin(admin), state)

        await _run(session_factory, h.cb_cancel, _callback(f'{h.CB_CANCEL}subscription_expired'), None, _admin(admin), state)

        assert await state.get_state() is None
        assert await get_overrides() == {}

    asyncio.run(scenario())


def test_button_text_flow(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await h.cb_button(_callback(f'{h.CB_BUTTON}winback'), _admin(admin), state)
        assert await state.get_state() == AdminTemplateStates.entering_button.state

        await _run(session_factory, h.on_button_text, _message('<b>жирная</b>'), None, _admin(admin), state)
        assert await get_overrides() == {} and await state.get_state() == AdminTemplateStates.entering_button.state

        await _run(session_factory, h.on_button_text, _message('Вернуться'), None, _admin(admin), state)
        assert (await get_overrides())['winback'].button_text == 'Вернуться' and await state.get_state() is None

        await h.cb_button(_callback(f'{h.CB_BUTTON}winback'), _admin(admin), state)
        await _run(session_factory, h.on_button_text, _message('-'), None, _admin(admin), state)  # «-» — заводская подпись
        assert (await get_overrides())['winback'].button_text is None

    asyncio.run(scenario())


def test_toggle_reset_and_test_send(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        await _run(session_factory, h.cb_toggle, _callback(f'{h.CB_TOGGLE}winback'), None, _admin(admin))
        assert (await get_overrides())['winback'].enabled is False
        await _run(session_factory, h.cb_toggle, _callback(f'{h.CB_TOGGLE}winback'), None, _admin(admin))
        assert (await get_overrides())['winback'].enabled is True

        await _run(session_factory, h.cb_reset, _callback(f'{h.CB_RESET}winback'), None, _admin(admin))
        assert await get_overrides() == {}

        callback = _callback(f'{h.CB_TEST}payment_success')
        await h.cb_test(callback, _admin(admin))
        kwargs = callback.bot.send_message.await_args.kwargs
        assert kwargs['chat_id'] == ADMIN_TG and kwargs['text'].startswith('✅ Оплата на сумму 249.00₽')

    asyncio.run(scenario())


def test_test_send_shows_telegram_rejection_as_alert(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            db.add(MessageTemplate(key='subscription_expired', template='<tg-emoji emoji-id="1">🏦</tg-emoji> x'))
            await db.commit()
        invalidate_cache()
        callback = _callback(f'{h.CB_TEST}subscription_expired')
        callback.bot.send_message.side_effect = TelegramBadRequest(
            method=SendMessage(chat_id=ADMIN_TG, text='x'), message='Bad Request: ENTITY_TEXT_INVALID'
        )

        await h.cb_test(callback, _admin(admin))

        args, kwargs = callback.answer.await_args
        assert kwargs.get('show_alert') is True and 'ENTITY_TEXT_INVALID' in args[0]

    asyncio.run(scenario())


def test_unknown_event_in_callback_is_handled(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        callback = _callback(f'{h.CB_CARD}no_such_event')

        await _run(session_factory, h.cb_card, callback, None, _admin(admin), _state())  # не должно бросать

        callback.answer.assert_awaited()

    asyncio.run(scenario())


def test_card_strips_tg_emoji_wrapper_from_current_text(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            db.add(MessageTemplate(key='subscription_expired', template='<tg-emoji emoji-id="1">🏦</tg-emoji> x'))
            await db.commit()
        invalidate_cache()
        callback = _callback(f'{h.CB_CARD}subscription_expired')

        await _run(session_factory, h.cb_card, callback, None, _admin(admin), _state())

        text, _ = _shown(callback)
        assert '<tg-emoji' not in text  # в карточке — только символ
        assert '🏦' in text

    asyncio.run(scenario())
