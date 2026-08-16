"""/admin — панель администратора: пользователи/тариф/промокоды/рассылка/статистика.
См. §11 clone-architecture.md. Доступ — только db_user.is_admin (см. AuthMiddleware,
который кладёт db_user во все хендлеры); при отсутствии доступа команда/колбэки
молча игнорируются (не раскрываем существование /admin посторонним).

Структура и UI-паттерны сознательно скопированы с реальной админки Bedolaga
(app/handlers/admin/* в remnawave-bedolaga-telegram-bot), но урезаны под наш
масштаб — см. диалог "берём его за основу, но упрощаем":
  - иерархия root -> раздел -> (подменю списки/создание) -> карточка, с "Назад"
    на НЕПОСРЕДСТВЕННОГО родителя (breadcrumb), а не всегда в корень;
  - визарды создания — пошаговый FSM-ввод текстом с заголовком "Шаг N/M";
  - списки (пользователи, промокоды) — пагинация "⬅️ [N/total] ➡️";
  - деструктивные действия (удаление промокода) — отдельный экран
    подтверждения "Да/Нет", НЕ show_alert;
  - булевы флаги (блокировка юзера, активность промокода) — toggle-кнопка,
    меняющая текст на том же экране, без ухода с него;
  - статистика — раздельные экраны (Пользователи/Подписки) с кнопкой "Обновить".
У Bedolaga под каждым из этих пунктов ещё промогруппы/кампании/RBAC/визарды
на 6+ шагов — вне нашего скоупа, мы сохранили СКЕЛЕТ паттернов, а не объём.

Проверка is_blocked: в этом модуле она не критична (админ по определению не
заблокирован сам себя), но чувствительные хендлеры support.py дополнительно
проверяют db_user.is_blocked сами (см. отчёт агента — рекомендация вынести это
в middleware осознанно НЕ реализована здесь, чтобы не создавать конфликт с
другими агентами, чьи хендлеры тоже должны будут учитывать блокировку).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PromoCode, Subscription, Tariff, Transaction, User
from app.states import AdminBroadcastStates, AdminEmojiStates, AdminPromoCodeStates, AdminTariffStates, AdminUserStates

logger = logging.getLogger(__name__)

router = Router(name='admin')

PAGE_SIZE = 10


# --- вспомогательные ---

CB_ADMIN_ROOT = 'admin:root'
CB_ADMIN_TARIFF = 'admin:tariff'
CB_ADMIN_BROADCAST = 'admin:broadcast'

CB_USERS_MENU = 'admin:users'
CB_USERS_SEARCH = 'admin:users:search'
CB_USERS_LIST = 'admin:users:list:'  # + page
CB_USER_CARD = 'admin:users:card:'  # + user_id
CB_USER_BLOCK_TOGGLE = 'admin:user:block_toggle:'  # + user_id

CB_TARIFF_EDIT_NAME = 'admin:tariff:edit:name'
CB_TARIFF_EDIT_TRAFFIC = 'admin:tariff:edit:traffic'
CB_TARIFF_EDIT_DEVICES = 'admin:tariff:edit:devices'
CB_TARIFF_EDIT_PERIOD = 'admin:tariff:edit:period:'  # + period key

CB_PROMO_MENU = 'admin:promo'
CB_PROMO_CREATE = 'admin:promo:create'
CB_PROMO_LIST = 'admin:promo:list:'  # + page
CB_PROMO_CARD = 'admin:promo:card:'  # + promo_id
CB_PROMO_TOGGLE = 'admin:promo:toggle:'  # + promo_id
CB_PROMO_DELETE = 'admin:promo:delete:'  # + promo_id
CB_PROMO_DELETE_YES = 'admin:promo:delete_yes:'  # + promo_id
CB_PROMO_TYPE = 'admin:promo:type:'  # + balance|days

CB_BROADCAST_AUDIENCE = 'admin:broadcast:audience:'  # + all|active|none
CB_BROADCAST_CONFIRM = 'admin:broadcast:confirm'
CB_BROADCAST_CANCEL = 'admin:broadcast:cancel'

CB_STATS_MENU = 'admin:stats'
CB_STATS_USERS = 'admin:stats:users'
CB_STATS_SUBS = 'admin:stats:subs'


def _is_admin(db_user: User | None) -> bool:
    return db_user is not None and db_user.is_admin


def _root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='👤 Пользователи', callback_data=CB_USERS_MENU)],
            [InlineKeyboardButton(text='💳 Тариф', callback_data=CB_ADMIN_TARIFF)],
            [InlineKeyboardButton(text='🎟 Промокоды', callback_data=CB_PROMO_MENU)],
            [InlineKeyboardButton(text='📢 Рассылка', callback_data=CB_ADMIN_BROADCAST)],
            [InlineKeyboardButton(text='📊 Статистика', callback_data=CB_STATS_MENU)],
        ]
    )


def _back_button(callback_data: str = CB_ADMIN_ROOT, text: str = '⬅️ Назад') -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def _back_keyboard(callback_data: str = CB_ADMIN_ROOT, text: str = '⬅️ Назад') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_back_button(callback_data, text)]])


def _pagination_row(prefix: str, page: int, total_pages: int) -> list[InlineKeyboardButton]:
    """Единая пагинация '⬅️ [N/total] ➡️' — тот же паттерн, что у Bedolaga."""
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text='⬅️', callback_data=f'{prefix}{page - 1}'))
    row.append(InlineKeyboardButton(text=f'{page + 1}/{max(total_pages, 1)}', callback_data='noop'))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(text='➡️', callback_data=f'{prefix}{page + 1}'))
    return row


async def _answer_or_edit(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == 'noop')
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# --- корневое меню ---


@router.message(Command('admin'))
async def cmd_admin(message: Message, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    await state.clear()
    await message.answer('🛠 Панель администратора', reply_markup=_root_keyboard())


@router.callback_query(F.data == CB_ADMIN_ROOT)
async def cb_admin_root(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    await _answer_or_edit(callback, '🛠 Панель администратора', _root_keyboard())
    await callback.answer()


# --- Добыча custom_emoji_id (см. диалог про кастомные премиум-эмодзи, app/emoji.py) ---


@router.message(Command('emojiid'))
async def cmd_emoji_id(message: Message, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    await state.set_state(AdminEmojiStates.awaiting_message)
    await message.answer(
        'Пришлите одним сообщением эмодзи (обычные или кастомные — из вашего Premium-набора), '
        'для которых нужен custom_emoji_id. Можно несколько штук подряд в одном сообщении.\n\n'
        'У обычных unicode-эмодзи ID не будет (это ожидаемо) — интересуют только те, что '
        'подсвечены Telegram как custom emoji (обычно из вашей Premium-панели эмодзи).'
    )


@router.message(AdminEmojiStates.awaiting_message)
async def on_emoji_id_message(message: Message, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await state.clear()
        return
    await state.clear()

    entities = message.entities or []
    custom = [e for e in entities if e.type == 'custom_emoji' and e.custom_emoji_id]

    if not custom:
        await message.answer(
            'В сообщении не нашлось custom_emoji-сущностей. Если вы отправляли обычные emoji '
            '(не из Premium-панели) — у них ID и не будет, это нормально, Telegram их не размечает.'
        )
        return

    text = message.text or ''
    lines = ['Найдены custom_emoji_id:']
    for e in custom:
        char = text[e.offset : e.offset + e.length]
        lines.append(f'{char} → <code>{e.custom_emoji_id}</code>')
    lines.append('\nВставьте нужный ID в app/emoji.py (Emoji(fallback=..., custom_id="...")).')

    await message.answer('\n'.join(lines))


# --- Пользователи ---


def _users_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔍 Поиск по ID', callback_data=CB_USERS_SEARCH)],
            [InlineKeyboardButton(text='📋 Список пользователей', callback_data=f'{CB_USERS_LIST}0')],
            [_back_button()],
        ]
    )


@router.callback_query(F.data == CB_USERS_MENU)
async def cb_users_menu(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    await _answer_or_edit(callback, '👤 <b>Пользователи</b>', _users_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == CB_USERS_SEARCH)
async def cb_users_search(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminUserStates.awaiting_telegram_id)
    await _answer_or_edit(callback, '🔍 Введите telegram_id пользователя:', _back_keyboard(CB_USERS_MENU))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_USERS_LIST))
async def cb_users_list(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    page = int(callback.data[len(CB_USERS_LIST):])

    total = (await db.execute(select(func.count(User.id)))).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)

    result = await db.execute(
        select(User).order_by(User.created_at.desc()).limit(PAGE_SIZE).offset(page * PAGE_SIZE)
    )
    users = result.scalars().all()

    rows = [
        [
            InlineKeyboardButton(
                text=f'{u.telegram_id} — @{u.username or "—"} — {u.balance_kopeks / 100:.0f}₽'
                + (' 🚫' if u.is_blocked else ''),
                callback_data=f'{CB_USER_CARD}{u.id}',
            )
        ]
        for u in users
    ]
    if rows:
        rows.append(_pagination_row(CB_USERS_LIST, page, total_pages))
    rows.append([_back_button(CB_USERS_MENU)])

    text = f'📋 <b>Пользователи</b> (всего: {total})' if users else 'Пользователей пока нет.'
    await _answer_or_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


def _user_card_keyboard(user: User) -> InlineKeyboardMarkup:
    block_text = '🔓 Разблокировать' if user.is_blocked else '🔒 Заблокировать'
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=block_text, callback_data=f'{CB_USER_BLOCK_TOGGLE}{user.id}')],
            [_back_button(CB_USERS_MENU)],
        ]
    )


async def _render_user_card(db: AsyncSession, user: User) -> str:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    sub_line = f'{sub.status} (до {sub.end_date:%Y-%m-%d %H:%M})' if sub else 'нет подписки'
    return (
        f'<b>Пользователь</b> {user.telegram_id} (@{user.username or "—"})\n'
        f'Регистрация: {user.created_at:%Y-%m-%d}\n'
        f'Баланс: {user.balance_kopeks / 100:.2f}₽\n'
        f'Подписка: {sub_line}\n'
        f'Заблокирован: {"да" if user.is_blocked else "нет"}'
    )


@router.message(AdminUserStates.awaiting_telegram_id, F.text.regexp(r'^\d+$'))
async def on_admin_user_id_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return

    telegram_id = int(message.text)
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    target = result.scalar_one_or_none()
    if target is None:
        await message.answer('Пользователь с таким telegram_id не найден.', reply_markup=_back_keyboard(CB_USERS_MENU))
        return

    await state.clear()
    text = await _render_user_card(db, target)
    await message.answer(text, reply_markup=_user_card_keyboard(target))


@router.callback_query(F.data.startswith(CB_USER_CARD))
async def cb_user_card(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target_id = int(callback.data[len(CB_USER_CARD):])
    target = await db.get(User, target_id)
    if target is None:
        await callback.answer('Пользователь не найден', show_alert=True)
        return
    text = await _render_user_card(db, target)
    await _answer_or_edit(callback, text, _user_card_keyboard(target))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_USER_BLOCK_TOGGLE))
async def cb_toggle_block(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target_id = int(callback.data[len(CB_USER_BLOCK_TOGGLE):])
    target = await db.get(User, target_id)
    if target is None:
        await callback.answer('Пользователь не найден', show_alert=True)
        return
    target.is_blocked = not target.is_blocked
    await db.flush()
    text = await _render_user_card(db, target)
    await _answer_or_edit(callback, text, _user_card_keyboard(target))
    await callback.answer('Статус обновлён')


# --- Тариф ---


async def _get_active_tariff(db: AsyncSession) -> Tariff | None:
    result = await db.execute(select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id))
    return result.scalars().first()


def _tariff_keyboard(tariff: Tariff) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='✏️ Название', callback_data=CB_TARIFF_EDIT_NAME)],
        [InlineKeyboardButton(text='✏️ Лимит трафика', callback_data=CB_TARIFF_EDIT_TRAFFIC)],
        [InlineKeyboardButton(text='✏️ Лимит устройств', callback_data=CB_TARIFF_EDIT_DEVICES)],
    ]
    for period in sorted(tariff.period_prices_kopeks.keys(), key=int):
        rows.append(
            [InlineKeyboardButton(text=f'✏️ Цена за {period} дн.', callback_data=f'{CB_TARIFF_EDIT_PERIOD}{period}')]
        )
    rows.append([_back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tariff_text(tariff: Tariff) -> str:
    traffic = 'безлимит' if tariff.traffic_limit_gb == 0 else f'{tariff.traffic_limit_gb} ГБ'
    lines = [
        f'<b>Тариф: {tariff.name}</b>',
        f'Лимит трафика: {traffic}',
        f'Лимит устройств: {tariff.device_limit}',
        '',
        'Цены по периодам:',
    ]
    for period, price in sorted(tariff.period_prices_kopeks.items(), key=lambda kv: int(kv[0])):
        lines.append(f'  {period} дн. — {price / 100:.2f}₽')
    return '\n'.join(lines)


@router.callback_query(F.data == CB_ADMIN_TARIFF)
async def cb_admin_tariff(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    tariff = await _get_active_tariff(db)
    if tariff is None:
        await _answer_or_edit(callback, 'Активный тариф не найден.', _back_keyboard())
        await callback.answer()
        return
    await _answer_or_edit(callback, _tariff_text(tariff), _tariff_keyboard(tariff))
    await callback.answer()


@router.callback_query(F.data == CB_TARIFF_EDIT_NAME)
async def cb_tariff_edit_name(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.update_data(tariff_field='name')
    await state.set_state(AdminTariffStates.entering_name)
    await _answer_or_edit(callback, '✏️ Введите новое название тарифа:', _back_keyboard(CB_ADMIN_TARIFF))
    await callback.answer()


@router.message(AdminTariffStates.entering_name, F.text)
async def on_admin_tariff_name_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    name = message.text.strip()
    if not (2 <= len(name) <= 64):
        await message.answer('Название должно быть от 2 до 64 символов.')
        return

    tariff = await _get_active_tariff(db)
    if tariff is None:
        await state.clear()
        return
    tariff.name = name
    await db.flush()
    await state.clear()
    await message.answer(f'✅ Название обновлено: {name}', reply_markup=_back_keyboard(CB_ADMIN_TARIFF))


@router.callback_query(F.data == CB_TARIFF_EDIT_TRAFFIC)
async def cb_tariff_edit_traffic(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminTariffStates.entering_prices)  # переиспользуем как "ждём число"
    await state.update_data(tariff_field='traffic')
    await _answer_or_edit(callback, '✏️ Введите лимит трафика в ГБ (0 = безлимит):', _back_keyboard(CB_ADMIN_TARIFF))
    await callback.answer()


@router.callback_query(F.data == CB_TARIFF_EDIT_DEVICES)
async def cb_tariff_edit_devices(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminTariffStates.entering_prices)
    await state.update_data(tariff_field='devices')
    await _answer_or_edit(callback, '✏️ Введите лимит устройств:', _back_keyboard(CB_ADMIN_TARIFF))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_TARIFF_EDIT_PERIOD))
async def cb_tariff_edit_period(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    period = callback.data[len(CB_TARIFF_EDIT_PERIOD):]
    await state.update_data(tariff_field='price', tariff_period=period)
    await state.set_state(AdminTariffStates.entering_prices)
    await _answer_or_edit(
        callback, f'✏️ Введите новую цену для периода {period} дней в рублях (например 299.00):', _back_keyboard(CB_ADMIN_TARIFF)
    )
    await callback.answer()


@router.message(AdminTariffStates.entering_prices, F.text)
async def on_admin_tariff_value_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    field = data.get('tariff_field')
    if field is None:
        await state.clear()
        return

    tariff = await _get_active_tariff(db)
    if tariff is None:
        await message.answer('Активный тариф не найден.')
        await state.clear()
        return

    if field == 'price':
        period = data.get('tariff_period')
        try:
            rub = float(message.text.replace(',', '.'))
            kopeks = round(rub * 100)
            if kopeks <= 0:
                raise ValueError
        except ValueError:
            await message.answer('Некорректная цена. Введите число, например 299.00')
            return
        prices = dict(tariff.period_prices_kopeks)
        prices[period] = kopeks
        tariff.period_prices_kopeks = prices
        result_text = f'✅ Цена для {period} дней обновлена: {kopeks / 100:.2f}₽'
    elif field in ('traffic', 'devices'):
        try:
            value = int(message.text.strip())
            if value < 0:
                raise ValueError
        except ValueError:
            await message.answer('Некорректное число. Введите целое число ≥ 0.')
            return
        if field == 'traffic':
            tariff.traffic_limit_gb = value
            result_text = f'✅ Лимит трафика обновлён: {"безлимит" if value == 0 else f"{value} ГБ"}'
        else:
            tariff.device_limit = value
            result_text = f'✅ Лимит устройств обновлён: {value}'
    else:
        await state.clear()
        return

    await db.flush()
    await state.clear()
    await message.answer(result_text, reply_markup=_back_keyboard(CB_ADMIN_TARIFF))


# --- Промокоды ---


def _promo_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='➕ Создать промокод', callback_data=CB_PROMO_CREATE)],
            [InlineKeyboardButton(text='📋 Список промокодов', callback_data=f'{CB_PROMO_LIST}0')],
            [_back_button()],
        ]
    )


@router.callback_query(F.data == CB_PROMO_MENU)
async def cb_promo_menu(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    await _answer_or_edit(callback, '🎟 <b>Промокоды</b>', _promo_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == CB_PROMO_CREATE)
async def cb_promo_create(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminPromoCodeStates.entering_code)
    await _answer_or_edit(
        callback, '🎟 <b>Шаг 1/4.</b> Введите читаемый код промокода (например SUMMER2026):', _back_keyboard(CB_PROMO_MENU)
    )
    await callback.answer()


@router.message(AdminPromoCodeStates.entering_code, F.text)
async def on_admin_promo_code_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    code = message.text.strip().upper()
    if not code or not code.replace('_', '').isalnum():
        await message.answer('Код должен состоять из латинских букв/цифр (можно "_"). Попробуйте снова.')
        return
    existing = await db.execute(select(PromoCode.id).where(PromoCode.code == code))
    if existing.scalar_one_or_none() is not None:
        await message.answer(f'Промокод {code} уже существует. Введите другой код.')
        return

    await state.update_data(promo_code=code)
    await state.set_state(AdminPromoCodeStates.entering_type)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='💰 Баланс', callback_data=f'{CB_PROMO_TYPE}balance'),
                InlineKeyboardButton(text='📅 Дни подписки', callback_data=f'{CB_PROMO_TYPE}days'),
            ],
            [_back_button(CB_PROMO_MENU)],
        ]
    )
    await message.answer('<b>Шаг 2/4.</b> Выберите тип промокода:', reply_markup=kb)


@router.callback_query(AdminPromoCodeStates.entering_type, F.data.startswith(CB_PROMO_TYPE))
async def cb_admin_promo_type(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    promo_type = callback.data[len(CB_PROMO_TYPE):]
    await state.update_data(promo_type=promo_type)
    await state.set_state(AdminPromoCodeStates.entering_value)
    unit = 'в рублях (начислится на баланс)' if promo_type == 'balance' else 'в днях (продлит подписку)'
    await _answer_or_edit(callback, f'<b>Шаг 3/4.</b> Введите значение промокода — {unit}:', _back_keyboard(CB_PROMO_MENU))
    await callback.answer()


@router.message(AdminPromoCodeStates.entering_value, F.text)
async def on_admin_promo_value_input(message: Message, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    promo_type = data.get('promo_type')
    if not data.get('promo_code') or not promo_type:
        await state.clear()
        return

    try:
        raw = float(message.text.replace(',', '.'))
        if raw <= 0:
            raise ValueError
    except ValueError:
        await message.answer('Некорректное значение. Введите положительное число.')
        return

    value = round(raw * 100) if promo_type == 'balance' else int(raw)
    await state.update_data(promo_value=value)
    await state.set_state(AdminPromoCodeStates.entering_max_activations)
    await message.answer('<b>Шаг 4/4.</b> Введите лимит активаций (сколько раз можно применить, например 100):')


@router.message(AdminPromoCodeStates.entering_max_activations, F.text)
async def on_admin_promo_max_activations_input(
    message: Message, db: AsyncSession, db_user: User | None, state: FSMContext
) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    code = data.get('promo_code')
    promo_type = data.get('promo_type')
    value = data.get('promo_value')
    if not code or not promo_type or value is None:
        await state.clear()
        return

    try:
        max_activations = int(message.text.strip())
        if max_activations <= 0:
            raise ValueError
    except ValueError:
        await message.answer('Некорректное число. Введите положительное целое число.')
        return

    existing = await db.execute(select(PromoCode.id).where(PromoCode.code == code))
    if existing.scalar_one_or_none() is not None:
        await message.answer(f'Промокод {code} уже существует (создан параллельно). Отменено.')
        await state.clear()
        return

    promo = PromoCode(
        code=code, type=promo_type, value=value, max_activations=max_activations, is_active=True, activations_count=0
    )
    db.add(promo)
    await db.flush()

    await state.clear()
    unit = '₽' if promo_type == 'balance' else 'дн.'
    display_value = value / 100 if promo_type == 'balance' else value
    await message.answer(
        f'✅ Промокод создан:\n<b>{code}</b> — {display_value}{unit}, лимит активаций: {max_activations}',
        reply_markup=_back_keyboard(CB_PROMO_MENU),
    )


@router.callback_query(F.data.startswith(CB_PROMO_LIST))
async def cb_promo_list(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    page = int(callback.data[len(CB_PROMO_LIST):])

    total = (await db.execute(select(func.count(PromoCode.id)))).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)

    result = await db.execute(
        select(PromoCode).order_by(PromoCode.created_at.desc()).limit(PAGE_SIZE).offset(page * PAGE_SIZE)
    )
    promos = result.scalars().all()

    rows = [
        [
            InlineKeyboardButton(
                text=f'{"✅" if p.is_active else "🚫"} {p.code} ({p.activations_count}/{p.max_activations})',
                callback_data=f'{CB_PROMO_CARD}{p.id}',
            )
        ]
        for p in promos
    ]
    if rows:
        rows.append(_pagination_row(CB_PROMO_LIST, page, total_pages))
    rows.append([_back_button(CB_PROMO_MENU)])

    text = f'📋 <b>Промокоды</b> (всего: {total})' if promos else 'Промокодов пока нет.'
    await _answer_or_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


def _promo_card_text(promo: PromoCode) -> str:
    unit = '₽' if promo.type == 'balance' else 'дн.'
    display_value = promo.value / 100 if promo.type == 'balance' else promo.value
    expires = promo.expires_at.strftime('%Y-%m-%d') if promo.expires_at else 'бессрочно'
    return (
        f'<b>Промокод {promo.code}</b>\n'
        f'Тип: {"баланс" if promo.type == "balance" else "дни подписки"}\n'
        f'Значение: {display_value}{unit}\n'
        f'Активаций: {promo.activations_count}/{promo.max_activations}\n'
        f'Истекает: {expires}\n'
        f'Активен: {"да" if promo.is_active else "нет"}'
    )


def _promo_card_keyboard(promo: PromoCode) -> InlineKeyboardMarkup:
    toggle_text = '🚫 Деактивировать' if promo.is_active else '✅ Активировать'
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=f'{CB_PROMO_TOGGLE}{promo.id}')],
            [InlineKeyboardButton(text='🗑️ Удалить', callback_data=f'{CB_PROMO_DELETE}{promo.id}')],
            [_back_button(f'{CB_PROMO_LIST}0')],
        ]
    )


@router.callback_query(F.data.startswith(CB_PROMO_CARD))
async def cb_promo_card(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    promo_id = int(callback.data[len(CB_PROMO_CARD):])
    promo = await db.get(PromoCode, promo_id)
    if promo is None:
        await callback.answer('Промокод не найден', show_alert=True)
        return
    await _answer_or_edit(callback, _promo_card_text(promo), _promo_card_keyboard(promo))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_PROMO_TOGGLE))
async def cb_promo_toggle(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    promo_id = int(callback.data[len(CB_PROMO_TOGGLE):])
    promo = await db.get(PromoCode, promo_id)
    if promo is None:
        await callback.answer('Промокод не найден', show_alert=True)
        return
    promo.is_active = not promo.is_active
    await db.flush()
    await _answer_or_edit(callback, _promo_card_text(promo), _promo_card_keyboard(promo))
    await callback.answer('Статус обновлён')


@router.callback_query(F.data.startswith(CB_PROMO_DELETE))
async def cb_promo_delete_confirm(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    promo_id = int(callback.data[len(CB_PROMO_DELETE):])
    promo = await db.get(PromoCode, promo_id)
    if promo is None:
        await callback.answer('Промокод не найден', show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='✅ Да, удалить', callback_data=f'{CB_PROMO_DELETE_YES}{promo_id}'),
                InlineKeyboardButton(text='❌ Отмена', callback_data=f'{CB_PROMO_CARD}{promo_id}'),
            ]
        ]
    )
    await _answer_or_edit(callback, f'Удалить промокод <b>{promo.code}</b>? Это необратимо.', kb)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_PROMO_DELETE_YES))
async def cb_promo_delete_yes(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    promo_id = int(callback.data[len(CB_PROMO_DELETE_YES):])
    promo = await db.get(PromoCode, promo_id)
    if promo is not None:
        await db.delete(promo)
        await db.flush()
    await callback.answer('Промокод удалён')
    await cb_promo_list_page0(callback, db, db_user)


async def cb_promo_list_page0(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    callback.data = f'{CB_PROMO_LIST}0'
    await cb_promo_list(callback, db, db_user)


# --- Рассылка ---

_BROADCAST_AUDIENCES = {
    'all': 'Всем пользователям',
    'active': 'С активной подпиской',
    'none': 'Без подписки',
}


def _broadcast_audience_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f'{CB_BROADCAST_AUDIENCE}{key}')]
        for key, label in _BROADCAST_AUDIENCES.items()
    ]
    rows.append([_back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _audience_telegram_ids(db: AsyncSession, audience: str) -> list[int]:
    if audience == 'active':
        result = await db.execute(
            select(User.telegram_id).join(Subscription, Subscription.user_id == User.id).where(
                Subscription.status == 'active'
            )
        )
    elif audience == 'none':
        result = await db.execute(
            select(User.telegram_id).outerjoin(Subscription, Subscription.user_id == User.id).where(
                Subscription.id.is_(None)
            )
        )
    else:
        result = await db.execute(select(User.telegram_id))
    return [row[0] for row in result.all()]


@router.callback_query(F.data == CB_ADMIN_BROADCAST)
async def cb_admin_broadcast(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    await _answer_or_edit(callback, '📢 <b>Шаг 1/2.</b> Выберите аудиторию рассылки:', _broadcast_audience_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith(CB_BROADCAST_AUDIENCE))
async def cb_broadcast_audience(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    audience = callback.data[len(CB_BROADCAST_AUDIENCE):]
    telegram_ids = await _audience_telegram_ids(db, audience)
    await state.update_data(broadcast_audience=audience)
    await state.set_state(AdminBroadcastStates.entering_text)
    await _answer_or_edit(
        callback,
        f'<b>Шаг 2/2.</b> Аудитория: {_BROADCAST_AUDIENCES[audience]} ({len(telegram_ids)} чел.)\n\n'
        f'Введите текст рассылки:',
        _back_keyboard(CB_ADMIN_BROADCAST),
    )
    await callback.answer()


@router.message(AdminBroadcastStates.entering_text, F.text)
async def on_admin_broadcast_text(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    audience = data.get('broadcast_audience', 'all')
    telegram_ids = await _audience_telegram_ids(db, audience)

    await state.update_data(broadcast_text=message.text)
    await state.set_state(AdminBroadcastStates.confirming)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='✅ Отправить', callback_data=CB_BROADCAST_CONFIRM),
                InlineKeyboardButton(text='❌ Отмена', callback_data=CB_BROADCAST_CANCEL),
            ]
        ]
    )
    await message.answer(
        f'Предпросмотр ({_BROADCAST_AUDIENCES[audience]}, {len(telegram_ids)} чел.):\n\n{message.text}\n\nОтправить?',
        reply_markup=kb,
    )


@router.callback_query(AdminBroadcastStates.confirming, F.data == CB_BROADCAST_CANCEL)
async def cb_admin_broadcast_cancel(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    await _answer_or_edit(callback, 'Рассылка отменена.', _back_keyboard())
    await callback.answer()


@router.callback_query(AdminBroadcastStates.confirming, F.data == CB_BROADCAST_CONFIRM)
async def cb_admin_broadcast_confirm(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    data = await state.get_data()
    text = data.get('broadcast_text')
    audience = data.get('broadcast_audience', 'all')
    await state.clear()
    if not text:
        await callback.answer()
        return

    await callback.answer('Рассылка запущена…')
    await _answer_or_edit(callback, 'Рассылка запущена, это может занять некоторое время…', _back_keyboard())

    telegram_ids = await _audience_telegram_ids(db, audience)

    sent, failed = 0, 0
    for telegram_id in telegram_ids:
        try:
            await callback.bot.send_message(telegram_id, text)
            sent += 1
        except Exception:
            failed += 1
            logger.debug('Рассылка: не удалось отправить %s', telegram_id, exc_info=True)
        await asyncio.sleep(0.05)

    await callback.message.answer(f'✅ Рассылка завершена. Доставлено: {sent}, не доставлено: {failed}.')


# --- Статистика ---


def _stats_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='👥 Пользователи', callback_data=CB_STATS_USERS)],
            [InlineKeyboardButton(text='💳 Подписки и доход', callback_data=CB_STATS_SUBS)],
            [_back_button()],
        ]
    )


@router.callback_query(F.data == CB_STATS_MENU)
async def cb_stats_menu(callback: CallbackQuery, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await _answer_or_edit(callback, '📊 <b>Статистика</b>', _stats_menu_keyboard())
    await callback.answer()


async def _render_users_stats(db: AsyncSession) -> str:
    now = datetime.now(timezone.utc)
    total = (await db.execute(select(func.count(User.id)))).scalar_one()
    blocked = (await db.execute(select(func.count(User.id)).where(User.is_blocked.is_(True)))).scalar_one()
    new_today = (
        await db.execute(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=1)))
    ).scalar_one()
    new_week = (
        await db.execute(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=7)))
    ).scalar_one()
    return (
        '👥 <b>Пользователи</b>\n\n'
        f'Всего: {total}\n'
        f'Заблокировано: {blocked}\n'
        f'Новых за сутки: {new_today}\n'
        f'Новых за неделю: {new_week}'
    )


@router.callback_query(F.data == CB_STATS_USERS)
async def cb_stats_users(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    text = await _render_users_stats(db)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Обновить', callback_data=CB_STATS_USERS)],
            [_back_button(CB_STATS_MENU)],
        ]
    )
    await _answer_or_edit(callback, text, kb)
    await callback.answer()


async def _render_subs_stats(db: AsyncSession) -> str:
    active = (await db.execute(select(func.count(Subscription.id)).where(Subscription.status == 'active'))).scalar_one()
    expired = (await db.execute(select(func.count(Subscription.id)).where(Subscription.status == 'expired'))).scalar_one()
    total = (await db.execute(select(func.count(Subscription.id)))).scalar_one()
    revenue_kopeks = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount_kopeks), 0)).where(
                Transaction.type.in_(['subscription_payment', 'topup']),
                Transaction.status == 'completed',
            )
        )
    ).scalar_one()
    return (
        '💳 <b>Подписки и доход</b>\n\n'
        f'Всего подписок: {total}\n'
        f'Активных: {active}\n'
        f'Истёкших: {expired}\n'
        f'Выручка (topup + подписки): {revenue_kopeks / 100:.2f}₽'
    )


@router.callback_query(F.data == CB_STATS_SUBS)
async def cb_stats_subs(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    text = await _render_subs_stats(db)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Обновить', callback_data=CB_STATS_SUBS)],
            [_back_button(CB_STATS_MENU)],
        ]
    )
    await _answer_or_edit(callback, text, kb)
    await callback.answer()


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
