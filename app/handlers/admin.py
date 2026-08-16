"""/admin — панель администратора: пользователи/тариф/промокоды/рассылка/статистика.
См. §11 clone-architecture.md. Доступ — только db_user.is_admin (см. AuthMiddleware,
который кладёт db_user во все хендлеры); при отсутствии доступа команда/колбэки
молча игнорируются (не раскрываем существование /admin посторонним).

Проверка is_blocked: в этом модуле она не критична (админ по определению не
заблокирован сам себя), но чувствительные хендлеры support.py дополнительно
проверяют db_user.is_blocked сами (см. отчёт агента — рекомендация вынести это
в middleware осознанно НЕ реализована здесь, чтобы не создавать конфликт с
другими агентами, чьи хендлеры тоже должны будут учитывать блокировку).
"""

from __future__ import annotations

import asyncio
import logging

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


# --- вспомогательные ---

CB_ADMIN_ROOT = 'admin:root'
CB_ADMIN_USERS = 'admin:users'
CB_ADMIN_TARIFF = 'admin:tariff'
CB_ADMIN_PROMO = 'admin:promo'
CB_ADMIN_BROADCAST = 'admin:broadcast'
CB_ADMIN_STATS = 'admin:stats'

CB_USER_BLOCK_TOGGLE = 'admin:user:block_toggle:'  # + user_id
CB_TARIFF_EDIT_PERIOD = 'admin:tariff:edit:'  # + period key
CB_PROMO_TYPE = 'admin:promo:type:'  # + balance|days
CB_BROADCAST_CONFIRM = 'admin:broadcast:confirm'
CB_BROADCAST_CANCEL = 'admin:broadcast:cancel'


def _is_admin(db_user: User | None) -> bool:
    return db_user is not None and db_user.is_admin


def _root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='👤 Пользователи', callback_data=CB_ADMIN_USERS)],
            [InlineKeyboardButton(text='💳 Тариф', callback_data=CB_ADMIN_TARIFF)],
            [InlineKeyboardButton(text='🎟 Промокоды', callback_data=CB_ADMIN_PROMO)],
            [InlineKeyboardButton(text='📢 Рассылка', callback_data=CB_ADMIN_BROADCAST)],
            [InlineKeyboardButton(text='📊 Статистика', callback_data=CB_ADMIN_STATS)],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='⬅️ В меню', callback_data=CB_ADMIN_ROOT)]])


async def _answer_or_edit(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)


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


@router.callback_query(F.data == CB_ADMIN_USERS)
async def cb_admin_users(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminUserStates.awaiting_telegram_id)
    await _answer_or_edit(callback, '👤 Введите telegram_id пользователя:', _back_keyboard())
    await callback.answer()


def _user_card_keyboard(user: User) -> InlineKeyboardMarkup:
    block_text = '🔓 Разблокировать' if user.is_blocked else '🔒 Заблокировать'
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=block_text, callback_data=f'{CB_USER_BLOCK_TOGGLE}{user.id}')],
            [InlineKeyboardButton(text='⬅️ В меню', callback_data=CB_ADMIN_ROOT)],
        ]
    )


async def _render_user_card(db: AsyncSession, user: User) -> str:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    sub_line = f'{sub.status} (до {sub.end_date:%Y-%m-%d %H:%M})' if sub else 'нет подписки'
    return (
        f'<b>Пользователь</b> {user.telegram_id} (@{user.username or "—"})\n'
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
        await message.answer('Пользователь с таким telegram_id не найден.', reply_markup=_back_keyboard())
        return

    await state.clear()
    text = await _render_user_card(db, target)
    await message.answer(text, reply_markup=_user_card_keyboard(target))


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


@router.callback_query(F.data == CB_ADMIN_TARIFF)
async def cb_admin_tariff(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    result = await db.execute(select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id))
    tariff = result.scalars().first()
    if tariff is None:
        await _answer_or_edit(callback, 'Активный тариф не найден.', _back_keyboard())
        await callback.answer()
        return

    lines = [f'<b>Тариф: {tariff.name}</b>', 'Цены по периодам (дней -> руб.):']
    buttons = []
    for period, price in sorted(tariff.period_prices_kopeks.items(), key=lambda kv: int(kv[0])):
        lines.append(f'  {period} дн. — {price / 100:.2f}₽')
        buttons.append([InlineKeyboardButton(text=f'✏️ {period} дн.', callback_data=f'{CB_TARIFF_EDIT_PERIOD}{period}')])
    buttons.append([InlineKeyboardButton(text='⬅️ В меню', callback_data=CB_ADMIN_ROOT)])

    await _answer_or_edit(callback, '\n'.join(lines), InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_TARIFF_EDIT_PERIOD))
async def cb_tariff_edit_period(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    period = callback.data[len(CB_TARIFF_EDIT_PERIOD):]
    await state.update_data(tariff_period=period)
    await state.set_state(AdminTariffStates.entering_prices)
    await _answer_or_edit(callback, f'Введите новую цену для периода {period} дней в рублях (например 299.00):', _back_keyboard())
    await callback.answer()


@router.message(AdminTariffStates.entering_prices, F.text)
async def on_admin_tariff_price_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    period = data.get('tariff_period')
    if period is None:
        await state.clear()
        return

    try:
        rub = float(message.text.replace(',', '.'))
        kopeks = round(rub * 100)
        if kopeks <= 0:
            raise ValueError
    except ValueError:
        await message.answer('Некорректная цена. Введите число, например 299.00')
        return

    result = await db.execute(select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id))
    tariff = result.scalars().first()
    if tariff is None:
        await message.answer('Активный тариф не найден.')
        await state.clear()
        return

    prices = dict(tariff.period_prices_kopeks)
    prices[period] = kopeks
    tariff.period_prices_kopeks = prices
    await db.flush()

    await state.clear()
    await message.answer(f'✅ Цена для {period} дней обновлена: {kopeks / 100:.2f}₽', reply_markup=_back_keyboard())


# --- Промокоды ---


@router.callback_query(F.data == CB_ADMIN_PROMO)
async def cb_admin_promo(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminPromoCodeStates.entering_code)
    await _answer_or_edit(callback, '🎟 Введите читаемый код промокода (например ADMIN2026):', _back_keyboard())
    await callback.answer()


@router.message(AdminPromoCodeStates.entering_code, F.text)
async def on_admin_promo_code_input(message: Message, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    code = message.text.strip().upper()
    if not code:
        await message.answer('Код не может быть пустым.')
        return
    await state.update_data(promo_code=code)
    await state.set_state(AdminPromoCodeStates.entering_type)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='💰 Баланс', callback_data=f'{CB_PROMO_TYPE}balance'),
                InlineKeyboardButton(text='📅 Дни подписки', callback_data=f'{CB_PROMO_TYPE}days'),
            ]
        ]
    )
    await message.answer('Выберите тип промокода:', reply_markup=kb)


@router.callback_query(AdminPromoCodeStates.entering_type, F.data.startswith(CB_PROMO_TYPE))
async def cb_admin_promo_type(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    promo_type = callback.data[len(CB_PROMO_TYPE):]
    await state.update_data(promo_type=promo_type)
    await state.set_state(AdminPromoCodeStates.entering_value)
    unit = 'копейках, введите сумму в рублях' if promo_type == 'balance' else 'днях'
    await _answer_or_edit(callback, f'Введите значение промокода ({unit}):')
    await callback.answer()


@router.message(AdminPromoCodeStates.entering_value, F.text)
async def on_admin_promo_value_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    code = data.get('promo_code')
    promo_type = data.get('promo_type')
    if not code or not promo_type:
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

    existing = await db.execute(select(PromoCode).where(PromoCode.code == code))
    if existing.scalar_one_or_none() is not None:
        await message.answer(f'Промокод {code} уже существует.')
        await state.clear()
        return

    promo = PromoCode(code=code, type=promo_type, value=value, is_active=True, activations_count=0)
    db.add(promo)
    await db.flush()

    await state.clear()
    await message.answer(f'✅ Промокод {code} создан ({promo_type}: {value}).', reply_markup=_back_keyboard())


# --- Рассылка ---


@router.callback_query(F.data == CB_ADMIN_BROADCAST)
async def cb_admin_broadcast(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminBroadcastStates.entering_text)
    await _answer_or_edit(callback, '📢 Введите текст рассылки:', _back_keyboard())
    await callback.answer()


@router.message(AdminBroadcastStates.entering_text, F.text)
async def on_admin_broadcast_text(message: Message, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
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
    await message.answer(f'Предпросмотр:\n\n{message.text}\n\nОтправить всем пользователям?', reply_markup=kb)


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
    await state.clear()
    if not text:
        await callback.answer()
        return

    await callback.answer('Рассылка запущена…')
    await _answer_or_edit(callback, 'Рассылка запущена, это может занять некоторое время…', _back_keyboard())

    result = await db.execute(select(User.telegram_id))
    telegram_ids = [row[0] for row in result.all()]

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


@router.callback_query(F.data == CB_ADMIN_STATS)
async def cb_admin_stats(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return

    users_count = (await db.execute(select(func.count(User.id)))).scalar_one()
    active_subs_count = (
        await db.execute(select(func.count(Subscription.id)).where(Subscription.status == 'active'))
    ).scalar_one()
    revenue_kopeks = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount_kopeks), 0)).where(
                Transaction.type.in_(['subscription_payment', 'topup']),
                Transaction.status == 'completed',
            )
        )
    ).scalar_one()

    text = (
        '📊 <b>Статистика</b>\n\n'
        f'Пользователей: {users_count}\n'
        f'Активных подписок: {active_subs_count}\n'
        f'Выручка (topup + subscription_payment): {revenue_kopeks / 100:.2f}₽'
    )
    await _answer_or_edit(callback, text, _back_keyboard())
    await callback.answer()


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
