"""Рассылка в боте — характеризация ДО выноса логики отправки в сервис
(docs/superpowers/plans/2026-09-22-broadcast-api.md). Тексты экранов, клавиатуры и содержимое
BroadcastHistory зафиксированы построчно; после Tasks 2 и 4 этот файл НЕ редактируется — бот
переходит на broadcast_service.run_broadcast_now, которое ждёт отправку целиком так же, как
прежний инлайн-цикл, поэтому наблюдаемое поведение не меняется."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage

from app.database.models import BroadcastHistory, Subscription, User
from app.handlers import admin as h
from app.states import AdminBroadcastStates
from tests.helpers import make_tariff, make_user

ADMIN_TG = 555


def _state() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=ADMIN_TG, user_id=ADMIN_TG))


def _admin(admin_id: int) -> User:
    return User(id=admin_id, telegram_id=ADMIN_TG, referral_code='a', is_admin=True)


def _callback(data: str, bot=None):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=ADMIN_TG),
        message=SimpleNamespace(
            edit_text=AsyncMock(), answer=AsyncMock(), answer_photo=AsyncMock(), edit_reply_markup=AsyncMock(),
        ),
        answer=AsyncMock(),
        bot=bot if bot is not None else AsyncMock(),
    )


def _message(text: str):
    return SimpleNamespace(text=text, answer=AsyncMock())


def _shown(callback) -> tuple[str, object]:
    """(текст, клавиатура) ПОСЛЕДНЕГО показанного экрана (edit_text либо answer)."""
    for method in (callback.message.edit_text, callback.message.answer):
        if method.await_args is not None:
            args, kwargs = method.await_args
            return args[0], kwargs.get('reply_markup')
    raise AssertionError('экран не показан')


def _buttons(markup) -> list:
    return [button for row in markup.inline_keyboard for button in row]


async def _add_subscription(factory, user_id: int, tariff_id: int, *, status: str, days_left: int) -> None:
    async with factory() as db:
        db.add(Subscription(
            user_id=user_id, tariff_id=tariff_id, status=status,
            end_date=datetime.now(timezone.utc) + timedelta(days=days_left),
        ))
        await db.commit()


def test_audience_screen_lists_categories_and_history_button(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            callback = _callback(h.CB_ADMIN_BROADCAST)
            state = _state()
            await h.cb_admin_broadcast(callback, _admin(admin_id), state)
            text, markup = _shown(callback)
            assert text == '🎯 <b>Выбор целевой аудитории</b>\n\nВыберите категорию пользователей для рассылки:'
            labels = [b.text for b in _buttons(markup)]
            assert labels == ['👥 Всем', '📱 С подпиской', '❌ Без подписки', '⏰ Истекающие', '🔚 Истёкшие',
                               '📦 По тарифу', '⬅️ Назад', '📋 История рассылок']
            assert (await state.get_state()) == AdminBroadcastStates.choosing_target.state

    asyncio.run(scenario())


def test_pick_target_shows_count_and_prompts_for_text(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        tariff_id = await make_tariff(session_factory)
        await make_user(session_factory, telegram_id=1)
        active_id = await make_user(session_factory, telegram_id=2)
        await _add_subscription(session_factory, active_id, tariff_id, status='active', days_left=10)

        async with session_factory() as db:
            callback = _callback(f'{h.CB_BROADCAST_TARGET}active')
            state = _state()
            await h.cb_broadcast_pick_target(callback, db, _admin(admin_id), state)
            text, markup = _shown(callback)
            assert text == (
                '📨 <b>Создание рассылки</b>\n\n🎯 <b>Аудитория:</b> 📱 С подпиской\n👥 <b>Получателей:</b> 1\n\n'
                'Введите текст сообщения (поддерживается HTML, до 4000 символов):'
            )
            assert (await state.get_state()) == AdminBroadcastStates.entering_text.state
            assert (await state.get_data())['broadcast_target'] == 'active'

    asyncio.run(scenario())


def test_text_over_4000_chars_is_rejected():
    async def scenario():
        message = _message('x' * 4001)
        await h.on_admin_broadcast_text(message, _admin(1), _state())
        message.answer.assert_awaited_once_with('❌ Сообщение слишком длинное (максимум 4000 символов)')

    asyncio.run(scenario())


async def _to_button_selector(state: FSMContext) -> SimpleNamespace:
    """Аудитория 'all' → текст → пропуск медиа → экран выбора кнопок. Возвращает callback последнего шага."""
    await state.update_data(broadcast_target='all', broadcast_text='Привет!')
    await state.set_state(AdminBroadcastStates.choosing_media)
    callback = _callback(f'{h.CB_BROADCAST_MEDIA}skip')
    await h.cb_broadcast_media_pick(callback, _admin(1), state)
    return callback


def test_skip_media_shows_button_selector_with_home_checked_by_default():
    async def scenario():
        state = _state()
        callback = await _to_button_selector(state)
        text, markup = _shown(callback)
        assert text.startswith('📘 <b>Выбор дополнительных кнопок</b>')
        marks = {b.text[0]: b.text for row in markup.inline_keyboard for b in row}
        home_button = next(b for row in markup.inline_keyboard for b in row if 'На главную' in b.text)
        assert home_button.text.startswith('✅')
        subscription_button = next(b for row in markup.inline_keyboard for b in row if 'Моя подписка' in b.text)
        assert subscription_button.text.startswith('⬜')
        assert (await state.get_state()) == AdminBroadcastStates.choosing_buttons.state

    asyncio.run(scenario())


def test_toggle_button_flips_the_checkmark():
    async def scenario():
        state = _state()
        await _to_button_selector(state)
        callback = _callback(f'{h.CB_BROADCAST_BTN_TOGGLE}referrals')
        await h.cb_broadcast_btn_toggle(callback, _admin(1), state)
        markup = callback.message.edit_reply_markup.await_args.kwargs['reply_markup']
        referrals_button = next(b for row in markup.inline_keyboard for b in row if 'Партнёрка' in b.text)
        assert referrals_button.text.startswith('✅')
        assert 'referrals' in (await state.get_data())['selected_buttons']

    asyncio.run(scenario())


def test_continue_shows_preview_with_audience_text_and_buttons(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await state.update_data(broadcast_target='all', broadcast_text='Привет всем!', selected_buttons=['home'])
        async with session_factory() as db:
            callback = _callback(h.CB_BROADCAST_BTN_CONTINUE)
            await h.cb_broadcast_btn_continue(callback, db, _admin(admin_id), state)
            text, markup = _shown(callback)
            assert '📨 <b>Предварительный просмотр рассылки</b>' in text
            assert '🎯 <b>Аудитория:</b> 👥 Всем' in text
            assert '📝 <b>Сообщение:</b>\nПривет всем!' in text
            assert '📘 <b>Кнопки:</b> 🏠 На главную' in text
            assert [b.text for b in _buttons(markup)] == ['✅ Отправить', '❌ Отмена']
            assert (await state.get_state()) == AdminBroadcastStates.confirming.state

    asyncio.run(scenario())


def test_confirm_sends_to_all_recipients_and_records_mixed_result(session_factory):
    """Цель 'all' включает и самого админа (он тоже строка в Users) — получателей 3:
    админу и одному пользователю письмо доходит, второй заблокировал бота — итог 'partial'."""

    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        ok_id = await make_user(session_factory, telegram_id=101)
        blocked_id = await make_user(session_factory, telegram_id=102)

        bot = AsyncMock()

        async def send_message_side_effect(chat_id, text, reply_markup=None):
            if chat_id == 102:
                raise TelegramForbiddenError(method=SendMessage(chat_id=102, text='x'), message='bot blocked')
            return SimpleNamespace(message_id=1)

        bot.send_message.side_effect = send_message_side_effect

        state = _state()
        await state.update_data(broadcast_target='all', broadcast_text='Привет!', selected_buttons=['home'])
        async with session_factory() as db:
            callback = _callback(h.CB_BROADCAST_CONFIRM, bot=bot)
            await h.cb_admin_broadcast_confirm(callback, db, _admin(admin_id), state)

            callback.answer.assert_any_await('Рассылка запущена…')
            text, markup = _shown(callback)
            assert text == (
                '✅ <b>Рассылка завершена!</b>\n\n📊 Отправлено: 2\n'
                '🚫 Заблокировали бота: 1\n❌ Не доставлено: 0\n'
                '👥 Всего: 3\n📈 Успешность: 66.7%'
            )

            history = (await db.execute(
                __import__('sqlalchemy').select(BroadcastHistory)
            )).scalars().one()
            assert history.status == 'partial'
            assert history.sent_count == 2
            assert history.blocked_count == 1
            assert history.failed_count == 0
            assert history.total_count == 3
            assert history.target_type == 'all'
            assert history.message_text == 'Привет!'
            assert history.admin_id == admin_id

            blocked_user = await db.get(User, blocked_id)
            ok_user = await db.get(User, ok_id)
            assert blocked_user.blocked_bot is True
            assert ok_user.blocked_bot is False

    asyncio.run(scenario())


def test_confirm_with_photo_sends_caption_when_short(session_factory):
    """Цель 'all' включает и самого админа — получателей 2 (админ + пользователь 201)."""

    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        await make_user(session_factory, telegram_id=201)

        bot = AsyncMock()
        state = _state()
        await state.update_data(
            broadcast_target='all', broadcast_text='Фото!', selected_buttons=['home'],
            has_media=True, media_type='photo', media_file_id='FILE1',
        )
        async with session_factory() as db:
            callback = _callback(h.CB_BROADCAST_CONFIRM, bot=bot)
            await h.cb_admin_broadcast_confirm(callback, db, _admin(admin_id), state)

        assert bot.send_photo.await_count == 2
        for _, kwargs in bot.send_photo.await_args_list:
            assert kwargs['photo'] == 'FILE1'
            assert kwargs['caption'] == 'Фото!'
        bot.send_message.assert_not_awaited()

    asyncio.run(scenario())


def test_confirm_retries_once_on_flood_control(session_factory, monkeypatch):
    """Цель 'all' включает и самого админа: его сообщение уходит сразу, а получателю 301
    один раз прилетает FloodWait — итог: 2 отправлено, 3 попытки send_message всего."""

    monkeypatch.setattr(h.asyncio, 'sleep', AsyncMock())

    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        await make_user(session_factory, telegram_id=301)

        bot = AsyncMock()
        call_counts: dict[int, int] = {}

        async def send_message_side_effect(chat_id, text, reply_markup=None):
            if chat_id == 301:
                call_counts[chat_id] = call_counts.get(chat_id, 0) + 1
                if call_counts[chat_id] == 1:
                    raise TelegramRetryAfter(
                        method=SendMessage(chat_id=301, text='x'), message='flood', retry_after=1
                    )
                return SimpleNamespace(message_id=2)
            return SimpleNamespace(message_id=1)

        bot.send_message.side_effect = send_message_side_effect
        state = _state()
        await state.update_data(broadcast_target='all', broadcast_text='Ретрай', selected_buttons=['home'])
        async with session_factory() as db:
            callback = _callback(h.CB_BROADCAST_CONFIRM, bot=bot)
            await h.cb_admin_broadcast_confirm(callback, db, _admin(admin_id), state)
            text, _ = _shown(callback)
            assert '📊 Отправлено: 2' in text
            assert bot.send_message.await_count == 3

    asyncio.run(scenario())


def test_history_screen_lists_completed_broadcast(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            db.add(BroadcastHistory(
                target_type='all', message_text='Тестовая рассылка', total_count=5, sent_count=5,
                status='completed', admin_id=admin_id, admin_name='boss',
            ))
            await db.commit()
            callback = _callback(f'{h.CB_BROADCAST_HISTORY}0')
            await h.cb_broadcast_history(callback, db, _admin(admin_id))
            text, markup = _shown(callback)
            assert '📋 <b>История рассылок</b> (стр. 1/1)' in text
            assert '✅' in text and '5/5 доставлено' in text and 'Тестовая рассылка' in text

    asyncio.run(scenario())
