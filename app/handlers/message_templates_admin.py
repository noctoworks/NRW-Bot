"""Редактор автоматических сообщений в админке бота: /admin → «✉️ Сообщения».

Текст присылается обычным сообщением: message.html_text превращает форматирование и Premium-эмодзи
(сущность custom_emoji) в HTML с <tg-emoji emoji-id="…">. Проверки и сохранение — в
app/services/message_templates (общие с веб-админкой). Экраны читают состояние из сессии обработчика,
а не из общего кэша: коммит делает AuthMiddleware ПОСЛЕ обработчика, и админ должен сразу видеть
только что сохранённое."""

from __future__ import annotations

import html
import re

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.handlers.admin import CB_ADMIN_ROOT, _answer_or_edit, _back_keyboard, _is_admin
from app.services.message_templates.registry import EVENTS, EventDef, UnknownEventError, get_event
from app.services.message_templates.service import (
    TemplateValidationError,
    build_preview,
    compose,
    load_overrides,
    reset_template,
    send_test_message,
    update_template,
)
from app.services.message_templates.validation import validate_button_text, validate_template
from app.states import AdminTemplateStates

router = Router(name='message_templates_admin')

CB_ROOT = 'tpl:root'
CB_CARD = 'tpl:card:'
CB_EDIT = 'tpl:edit:'
CB_BUTTON = 'tpl:btn:'
CB_TOGGLE = 'tpl:toggle:'
CB_RESET = 'tpl:reset:'
CB_TEST = 'tpl:test:'
CB_SAVE = 'tpl:save'
CB_CANCEL = 'tpl:cancel:'

_TG_EMOJI_RE = re.compile(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', re.S)


def _plain(text: str) -> str:
    """Для показа внутри служебных сообщений: <tg-emoji> заменяем символом (отображение не должно
    зависеть от Premium; настоящий вид проверяется кнопкой «Тест мне»)."""
    return _TG_EMOJI_RE.sub(r'\1', text)


def _key_from(data: str, prefix: str) -> str:
    return data[len(prefix):]


def _event_or_none(key: str) -> EventDef | None:
    try:
        return get_event(key)
    except UnknownEventError:
        return None


# --- экраны ------------------------------------------------------------------------------------------------


async def _root_screen(db: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    overrides = await load_overrides(db)
    rows = []
    for event in EVENTS:
        override = overrides.get(event.key)
        mark = '🚫' if override is not None and not override.enabled else '✅'
        edited = ' ✏️' if override is not None and override.template is not None else ''
        rows.append([InlineKeyboardButton(text=f'{mark} {event.title}{edited}', callback_data=f'{CB_CARD}{event.key}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=CB_ADMIN_ROOT)])
    text = (
        '✉️ <b>Автоматические сообщения бота</b>\n\n'
        'Выберите сообщение, чтобы посмотреть и изменить его текст.\n'
        '✅ включено · 🚫 выключено · ✏️ текст изменён'
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _card_screen(event: EventDef, db: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    override = (await load_overrides(db)).get(event.key)
    rendered = compose(event, override, event.samples())
    enabled = override.enabled if override is not None else True
    customised = override is not None and override.template is not None
    variables = '\n'.join(
        f'• <code>{{{v.name}}}</code> — {html.escape(v.description)}' for v in event.variables
    ) or '• нет переменных'
    lines = [
        f'✉️ <b>{html.escape(event.title)}</b>',
        f'Когда отправляется: {html.escape(event.trigger)}',
        f'Статус: {"✅ включено" if enabled else "🚫 выключено"} · {"✏️ текст изменён" if customised else "заводской текст"}',
        '',
        'Переменные:',
        variables,
        '',
        'Как выглядит сейчас (с примерами):',
        '———',
        _plain(rendered.text),
        '———',
    ]
    if rendered.button_text:
        lines.append(f'Кнопка: «{html.escape(rendered.button_text)}»')
    keyboard = [[InlineKeyboardButton(text='✏️ Изменить текст', callback_data=f'{CB_EDIT}{event.key}')]]
    if event.has_button:
        keyboard.append([InlineKeyboardButton(text='🔘 Текст кнопки', callback_data=f'{CB_BUTTON}{event.key}')])
    keyboard.append(
        [InlineKeyboardButton(text='🔕 Выключить' if enabled else '🔔 Включить', callback_data=f'{CB_TOGGLE}{event.key}')]
    )
    keyboard.append(
        [
            InlineKeyboardButton(text='📨 Тест мне', callback_data=f'{CB_TEST}{event.key}'),
            InlineKeyboardButton(text='↩️ Сбросить', callback_data=f'{CB_RESET}{event.key}'),
        ]
    )
    keyboard.append([InlineKeyboardButton(text='⬅️ К списку', callback_data=CB_ROOT)])
    return '\n'.join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard)


def _errors_text(errors: list[str]) -> str:
    return '❌ Не удалось сохранить:\n' + '\n'.join(f'• {html.escape(error)}' for error in errors)


# --- обработчики -------------------------------------------------------------------------------------------


@router.callback_query(F.data == CB_ROOT)
async def cb_root(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    await state.clear()
    text, keyboard = await _root_screen(db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_CARD))
async def cb_card(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_CARD))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    await state.clear()
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_EDIT))
async def cb_edit(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_EDIT))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    await state.update_data(template_key=event.key)
    await state.set_state(AdminTemplateStates.entering_text)
    variables = ', '.join(f'<code>{{{name}}}</code>' for name in event.variable_names) or 'нет'
    required = (
        '\nОбязательно: ' + ', '.join('{' + name + '}' for name in event.required_variables)
        if event.required_variables
        else ''
    )
    text = (
        f'✏️ <b>{html.escape(event.title)}</b>\n\n'
        'Пришлите новый текст ОДНИМ сообщением. Можно использовать форматирование Telegram и Premium-эмодзи — '
        'бот сохранит их как есть.\n'
        f'Переменные (вставьте в текст как есть): {variables}{html.escape(required)}'
    )
    await _answer_or_edit(callback, text, _back_keyboard(f'{CB_CARD}{event.key}', '↩️ Отмена'))
    await callback.answer()


@router.message(AdminTemplateStates.entering_text, F.text)
async def on_template_text(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none((await state.get_data()).get('template_key') or '')
    if event is None:
        await state.clear()
        return
    new_html = message.html_text
    result = validate_template(event, new_html)
    if not result.ok:
        await message.answer(_errors_text(result.errors) + '\n\nПришлите исправленный текст или нажмите «Отмена».')
        return
    await state.update_data(pending_html=new_html)
    await state.set_state(AdminTemplateStates.confirming)
    preview = await build_preview(event.key, template=new_html)
    warnings = ''.join(f'\n\n⚠️ {html.escape(warning)}' for warning in result.warnings)
    await message.answer(
        f'Предпросмотр (с примерами переменных):\n———\n{_plain(preview.text)}\n———{warnings}',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text='✅ Сохранить', callback_data=CB_SAVE)],
                [InlineKeyboardButton(text='↩️ Отмена', callback_data=f'{CB_CANCEL}{event.key}')],
            ]
        ),
    )


@router.message(AdminTemplateStates.entering_text)
async def on_template_not_text(message: Message, db_user: User | None) -> None:
    if _is_admin(db_user):
        await message.answer('Пришлите текст сообщением (можно с форматированием и эмодзи).')


@router.callback_query(F.data == CB_SAVE, AdminTemplateStates.confirming)
async def cb_save(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    event = _event_or_none(data.get('template_key') or '')
    pending = data.get('pending_html')
    if event is None or pending is None:
        await state.clear()
        await callback.answer('Нечего сохранять', show_alert=True)
        return
    try:
        await update_template(db, event.key, admin_user_id=db_user.id, template=pending)
    except TemplateValidationError as error:
        await callback.answer('; '.join(error.errors)[:190], show_alert=True)
        return
    await state.clear()
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, '✅ Сохранено\n\n' + text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_CANCEL))
async def cb_cancel(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    await state.clear()
    event = _event_or_none(_key_from(callback.data, CB_CANCEL))
    if event is None:
        await callback.answer()
        return
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer('Отменено')


@router.callback_query(F.data.startswith(CB_BUTTON))
async def cb_button(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_BUTTON))
    if event is None or not event.has_button:
        await callback.answer('У этого сообщения нет кнопки', show_alert=True)
        return
    await state.update_data(template_key=event.key)
    await state.set_state(AdminTemplateStates.entering_button)
    await _answer_or_edit(
        callback,
        '🔘 Пришлите новую подпись кнопки (до 64 символов, без форматирования и без кастомных эмодзи).\n'
        f'Символ «-» вернёт заводскую подпись: «{html.escape(event.button_label(True) or "")}».',
        _back_keyboard(f'{CB_CARD}{event.key}', '↩️ Отмена'),
    )
    await callback.answer()


@router.message(AdminTemplateStates.entering_button, F.text)
async def on_button_text(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none((await state.get_data()).get('template_key') or '')
    if event is None:
        await state.clear()
        return
    label = (message.text or '').strip()
    value: str | None = None if label == '-' else label
    errors = validate_button_text(event, value) if value is not None else []
    if errors:
        await message.answer(_errors_text(errors) + '\n\nПришлите другую подпись или нажмите «Отмена».')
        return
    await update_template(db, event.key, admin_user_id=db_user.id, button_text=value)
    await state.clear()
    text, keyboard = await _card_screen(event, db)
    await message.answer('✅ Сохранено\n\n' + text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(CB_TOGGLE))
async def cb_toggle(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_TOGGLE))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    override = (await load_overrides(db)).get(event.key)
    currently_enabled = override.enabled if override is not None else True
    await update_template(db, event.key, admin_user_id=db_user.id, enabled=not currently_enabled)
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer('Включено' if not currently_enabled else 'Выключено')


@router.callback_query(F.data.startswith(CB_RESET))
async def cb_reset(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_RESET))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    await reset_template(db, event.key, admin_user_id=db_user.id)
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer('Сброшено к заводскому')


@router.callback_query(F.data.startswith(CB_TEST))
async def cb_test(callback: CallbackQuery, db_user: User | None) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_TEST))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    try:
        await send_test_message(callback.bot, telegram_id=callback.from_user.id, key=event.key)
    except TelegramBadRequest as error:
        await callback.answer(f'Telegram отклонил сообщение: {error.message}'[:190], show_alert=True)
        return
    except Exception:
        await callback.answer('Не удалось отправить тестовое сообщение', show_alert=True)
        return
    await callback.answer('📨 Отправлено вам в чат')


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
