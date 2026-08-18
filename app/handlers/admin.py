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
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import BroadcastHistory, PromoCode, Subscription, Tariff, Transaction, User
from app.handlers.promocode import CB_PROMO_ENTER
from app.handlers.subscription import get_active_tariffs
from app.keyboards.main_menu import (
    CB_ADMIN_ROOT,
    CB_MENU_MAIN,
    CB_REFERRAL_MENU,
    CB_SUBSCRIPTION_MY,
    CB_SUBSCRIPTION_RENEW,
    CB_SUPPORT_MENU,
)
from app.services.notification_service import notify_balance_changed
from app.states import AdminBroadcastStates, AdminEmojiStates, AdminPromoCodeStates, AdminTariffStates, AdminUserStates

logger = logging.getLogger(__name__)

router = Router(name='admin')

PAGE_SIZE = 10


# --- вспомогательные ---

CB_ADMIN_TARIFF = 'admin:tariff'
CB_ADMIN_BROADCAST = 'admin:broadcast'
CB_ADMIN_SERVERS = 'admin:servers'

CB_USERS_ROOT = 'admin:usersroot'  # подменю "Юзеры/Подписки" (Bedolaga: admin_submenu_users)
CB_USERS_MENU = 'admin:users'  # экран "Управление пользователями"
CB_USERS_SEARCH = 'admin:users:search'
CB_USERS_LIST = 'admin:users:list:'  # + page
CB_USERS_INACTIVE = 'admin:users:inactive:'  # + page — без подписки
CB_USERS_BLACKLIST = 'admin:users:blacklist:'  # + page — is_blocked
CB_USERS_BLOCKED_BOT = 'admin:users:blockedbot:'  # + page — заблокировали бота
CB_USERS_MASSBAN = 'admin:users:massban'
CB_PARTNERS_MENU = 'admin:partners'
CB_SUBS_MENU = 'admin:subs:'  # + page

CB_USER_CARD = 'admin:users:card:'  # + user_id
CB_USER_BLOCK_TOGGLE = 'admin:user:block_toggle:'  # + user_id
CB_USER_DELETE = 'admin:user:delete:'  # + user_id
CB_USER_DELETE_YES = 'admin:user:delete_yes:'  # + user_id
CB_USER_BALANCE = 'admin:user:balance:'  # + user_id
CB_USER_MESSAGE = 'admin:user:message:'  # + user_id
CB_USER_REFERRALS = 'admin:user:referrals:'  # + user_id
CB_USER_TRANSACTIONS = 'admin:user:transactions:'  # + user_id

CB_TARIFF_EDIT_NAME = 'admin:tariff:edit:name'
CB_TARIFF_EDIT_TRAFFIC = 'admin:tariff:edit:traffic'
CB_TARIFF_EDIT_DEVICES = 'admin:tariff:edit:devices'
CB_TARIFF_EDIT_PERIOD = 'admin:tariff:edit:period:'  # + period key
CB_TARIFF_TOGGLE_TRIAL = 'admin:tariff:toggle_trial:'  # + tariff_id
CB_TARIFF_EDIT_TRIAL_DAYS = 'admin:tariff:edit:trial_days'

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
    """Раскладка 2 в ряд — см. диалог/референс-скрин "Административная панель".
    У Bedolaga тут ещё Серверы/Цены/Триалы/Настройки/Система/Пополнения как
    отдельные CRUD-разделы с собственными подсистемами (RBAC, ноды Remnawave,
    очередь заявок на пополнение и т.д.) — вне нашего масштаба; вместо
    пустых заглушек оставили только то, для чего есть реальные данные."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='👥 Юзеры/Подписки', callback_data=CB_USERS_ROOT),
                InlineKeyboardButton(text='🌐 Серверы', callback_data=CB_ADMIN_SERVERS),
            ],
            [
                InlineKeyboardButton(text='📦 Тарифы', callback_data=CB_ADMIN_TARIFF),
                InlineKeyboardButton(text='🎟 Промокоды', callback_data=CB_PROMO_MENU),
            ],
            [
                InlineKeyboardButton(text='📊 Статистика', callback_data=CB_STATS_MENU),
                InlineKeyboardButton(text='📢 Рассылка', callback_data=CB_ADMIN_BROADCAST),
            ],
        ]
    )


async def _render_root_header(db: AsyncSession) -> str:
    """'Онлайн сейчас/сегодня/за неделю' — см. диалог/референс-скрин. У нас нет
    настоящего realtime-presence (websocket/heartbeat), поэтому приближаем через
    last_activity_at: "сейчас" = последние 5 минут, "сегодня"/"неделя" аналогично
    Bedolaga (уникальные пользователи с активностью в окне)."""
    now = datetime.now(timezone.utc)
    online_now = (
        await db.execute(select(func.count(User.id)).where(User.last_activity_at >= now - timedelta(minutes=5)))
    ).scalar_one()
    online_today = (
        await db.execute(select(func.count(User.id)).where(User.last_activity_at >= now - timedelta(days=1)))
    ).scalar_one()
    online_week = (
        await db.execute(select(func.count(User.id)).where(User.last_activity_at >= now - timedelta(days=7)))
    ).scalar_one()
    return (
        '🛠 <b>Административная панель</b>\n\n'
        f'🟢 Онлайн сейчас: {online_now}\n'
        f'📅 Онлайн сегодня: {online_today}\n'
        f'📊 На этой неделе: {online_week}\n\n'
        'Выберите раздел для управления:'
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
async def cmd_admin(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    await state.clear()
    await message.answer(await _render_root_header(db), reply_markup=_root_keyboard())


@router.callback_query(F.data == CB_ADMIN_ROOT)
async def cb_admin_root(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    await _answer_or_edit(callback, await _render_root_header(db), _root_keyboard())
    await callback.answer()


# --- Серверы (read-only список сквадов из Remnawave, см. scripts/seed.py) ---


@router.callback_query(F.data == CB_ADMIN_SERVERS)
async def cb_admin_servers(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    from app.database.models import ServerSquad

    result = await db.execute(select(ServerSquad).order_by(ServerSquad.id))
    squads = result.scalars().all()
    if not squads:
        text = '🌐 <b>Серверы</b>\n\nСквадов пока нет (запустите scripts/seed.py).'
    else:
        lines = ['🌐 <b>Серверы</b>', '']
        for s in squads:
            status = '✅' if s.is_active else '🚫'
            lines.append(f'{status} {s.name} ({s.country or "—"}) — <code>{s.squad_uuid}</code>')
        text = '\n'.join(lines)
    await _answer_or_edit(callback, text, _back_keyboard())
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


# --- Юзеры/Подписки: подменю (см. диалог/референс-скрин "Управление пользователями и подписками") ---


def _users_root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='👥 Пользователи', callback_data=CB_USERS_MENU),
                InlineKeyboardButton(text='🤝 Партнёрка', callback_data=CB_PARTNERS_MENU),
            ],
            [InlineKeyboardButton(text='📱 Подписки', callback_data=f'{CB_SUBS_MENU}0')],
            [_back_button()],
        ]
    )


@router.callback_query(F.data == CB_USERS_ROOT)
async def cb_users_root(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    await _answer_or_edit(callback, '👥 <b>Управление пользователями и подписками</b>\n\nВыберите нужный раздел:', _users_root_keyboard())
    await callback.answer()


# --- Пользователи ---


def _time_ago(dt: datetime | None) -> str:
    if dt is None:
        return '—'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    seconds = delta.total_seconds()
    if seconds < 3600:
        return f'{max(1, int(seconds // 60))} мин. назад'
    if seconds < 86400:
        return f'{int(seconds // 3600)} ч. назад'
    if seconds < 172800:
        return 'вчера'
    return f'{int(seconds // 86400)} дн. назад'


def _users_menu_keyboard() -> InlineKeyboardMarkup:
    """Часть кнопок референса (⚙️ Фильтры — конструктор произвольных фильтров) —
    вне нашего масштаба, см. диалог; вместо неё оставлены конкретные готовые
    списки (все реализованы, не заглушки)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='👥 Все пользователи', callback_data=f'{CB_USERS_LIST}0'),
                InlineKeyboardButton(text='🔍 Поиск', callback_data=CB_USERS_SEARCH),
            ],
            [
                InlineKeyboardButton(text='🗑️ Неактивные', callback_data=f'{CB_USERS_INACTIVE}0'),
                InlineKeyboardButton(text='🔒 Чёрный список', callback_data=f'{CB_USERS_BLACKLIST}0'),
            ],
            [
                InlineKeyboardButton(text='🔴 Массовый бан', callback_data=CB_USERS_MASSBAN),
                InlineKeyboardButton(text='🚫 Заблокир. бота', callback_data=f'{CB_USERS_BLOCKED_BOT}0'),
            ],
            [_back_button(CB_USERS_ROOT)],
        ]
    )


async def _render_users_menu_header(db: AsyncSession) -> str:
    now = datetime.now(timezone.utc)
    total = (await db.execute(select(func.count(User.id)))).scalar_one()
    active = (await db.execute(select(func.count(User.id)).where(User.is_blocked.is_(False)))).scalar_one()
    blocked = (await db.execute(select(func.count(User.id)).where(User.is_blocked.is_(True)))).scalar_one()
    new_today = (
        await db.execute(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=1)))
    ).scalar_one()
    new_week = (
        await db.execute(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=7)))
    ).scalar_one()
    new_month = (
        await db.execute(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=30)))
    ).scalar_one()
    return (
        '👥 <b>Управление пользователями</b>\n\n'
        '📊 Статистика:\n'
        f'• Всего: {total}\n'
        f'• Активных: {active}\n'
        f'• Заблокированных: {blocked}\n\n'
        '📈 Новые пользователи:\n'
        f'• Сегодня: {new_today}\n'
        f'• За неделю: {new_week}\n'
        f'• За месяц: {new_month}\n\n'
        'Выберите действие:'
    )


@router.callback_query(F.data == CB_USERS_MENU)
async def cb_users_menu(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    await _answer_or_edit(callback, await _render_users_menu_header(db), _users_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == CB_USERS_SEARCH)
async def cb_users_search(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminUserStates.awaiting_telegram_id)
    await _answer_or_edit(callback, '🔍 Введите telegram_id пользователя:', _back_keyboard(CB_USERS_MENU))
    await callback.answer()


async def _render_users_list(
    callback: CallbackQuery, db: AsyncSession, page: int, list_prefix: str, where_clause, empty_text: str
) -> None:
    count_stmt = select(func.count(User.id))
    # selectinload обязателен: без него user.subscription ниже — ленивая
    # relationship, а AsyncSession не поддерживает lazy-load вне greenlet-контекста
    # (падает MissingGreenlet). Поймано вживую тестовым скриптом перед выкаткой.
    list_stmt = select(User).options(selectinload(User.subscription)).order_by(User.created_at.desc())
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
        list_stmt = list_stmt.where(where_clause)

    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    users = (await db.execute(list_stmt.limit(PAGE_SIZE).offset(page * PAGE_SIZE))).scalars().all()

    rows = []
    for u in users:
        status_icon = '🚫' if u.is_blocked else '✅'
        sub_icon = '💎' if u.subscription and u.subscription.status == 'active' else '❌'
        label = u.username or f'id{u.telegram_id}'
        rows.append(
            [
                InlineKeyboardButton(
                    text=f'{status_icon}{sub_icon} {label} | 📆 {_time_ago(u.last_activity_at)}',
                    callback_data=f'{CB_USER_CARD}{u.id}',
                )
            ]
        )
    if rows:
        rows.append(_pagination_row(list_prefix, page, total_pages))
    rows.append([_back_button(CB_USERS_MENU)])

    text = f'📋 <b>Список пользователей</b> (стр. {page + 1}/{total_pages})' if users else empty_text
    await _answer_or_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_USERS_LIST))
async def cb_users_list(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    page = int(callback.data[len(CB_USERS_LIST):])
    await _render_users_list(callback, db, page, CB_USERS_LIST, None, 'Пользователей пока нет.')


@router.callback_query(F.data.startswith(CB_USERS_INACTIVE))
async def cb_users_inactive(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    """"Неактивные" — без подписки (нет реального concept триала/оффлайна дольше
    N дней в нашей схеме, см. диалог про упрощение) — читаемое и честное определение."""
    if not _is_admin(db_user):
        await callback.answer()
        return
    page = int(callback.data[len(CB_USERS_INACTIVE):])
    await _render_users_list(
        callback, db, page, CB_USERS_INACTIVE, ~User.subscription.has(), 'Неактивных пользователей нет.'
    )


@router.callback_query(F.data.startswith(CB_USERS_BLACKLIST))
async def cb_users_blacklist(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    page = int(callback.data[len(CB_USERS_BLACKLIST):])
    await _render_users_list(
        callback, db, page, CB_USERS_BLACKLIST, User.is_blocked.is_(True), 'Чёрный список пуст.'
    )


@router.callback_query(F.data.startswith(CB_USERS_BLOCKED_BOT))
async def cb_users_blocked_bot(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    page = int(callback.data[len(CB_USERS_BLOCKED_BOT):])
    await _render_users_list(
        callback, db, page, CB_USERS_BLOCKED_BOT, User.blocked_bot.is_(True), 'Никто не блокировал бота (пока).'
    )


@router.callback_query(F.data == CB_USERS_MASSBAN)
async def cb_users_massban(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.set_state(AdminUserStates.awaiting_massban_ids)
    await _answer_or_edit(
        callback,
        '🔴 <b>Массовый бан</b>\n\nПришлите telegram_id через запятую или с новой строки:',
        _back_keyboard(CB_USERS_MENU),
    )
    await callback.answer()


@router.message(AdminUserStates.awaiting_massban_ids, F.text)
async def on_admin_massban_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    await state.clear()
    raw_ids = [chunk.strip() for chunk in message.text.replace('\n', ',').split(',') if chunk.strip()]
    telegram_ids = [int(x) for x in raw_ids if x.isdigit()]
    if not telegram_ids:
        await message.answer('Не нашёл ни одного telegram_id.', reply_markup=_back_keyboard(CB_USERS_MENU))
        return

    result = await db.execute(update(User).where(User.telegram_id.in_(telegram_ids)).values(is_blocked=True))
    await db.commit()
    await message.answer(
        f'✅ Заблокировано пользователей: {result.rowcount} из {len(telegram_ids)} присланных id.',
        reply_markup=_back_keyboard(CB_USERS_MENU),
    )


def _user_card_keyboard(user: User) -> InlineKeyboardMarkup:
    block_text = '🔓 Разблокировать' if user.is_blocked else '🚫 Заблокировать'
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='💰 Баланс', callback_data=f'{CB_USER_BALANCE}{user.id}'),
                InlineKeyboardButton(text='🤝 Рефералы', callback_data=f'{CB_USER_REFERRALS}{user.id}'),
            ],
            [
                InlineKeyboardButton(text='📋 Транзакции', callback_data=f'{CB_USER_TRANSACTIONS}{user.id}'),
                InlineKeyboardButton(text='✉️ Сообщение', callback_data=f'{CB_USER_MESSAGE}{user.id}'),
            ],
            [
                InlineKeyboardButton(text=block_text, callback_data=f'{CB_USER_BLOCK_TOGGLE}{user.id}'),
                InlineKeyboardButton(text='🗑️ Удалить', callback_data=f'{CB_USER_DELETE}{user.id}'),
            ],
            [_back_button(CB_USERS_MENU)],
        ]
    )


async def _render_user_card(db: AsyncSession, user: User) -> str:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    tx_count = (
        await db.execute(select(func.count(Transaction.id)).where(Transaction.user_id == user.id))
    ).scalar_one()
    days_registered = (datetime.now(timezone.utc) - user.created_at.replace(tzinfo=timezone.utc)).days

    lines = [
        '👤 <b>Управление пользователем</b>',
        '',
        '<b>Основная информация:</b>',
        f'• ID: <code>{user.telegram_id}</code>',
        f'• Username: @{user.username or "—"}',
        f'• Статус: {"🚫 Заблокирован" if user.is_blocked else "✅ Активен"}',
        f'• Язык: {user.language}',
        '',
        '<b>Финансы:</b>',
        f'• Баланс: {user.balance_kopeks / 100:.2f} ₽',
        f'• Транзакций: {tx_count}',
        '',
        '<b>Активность:</b>',
        f'• Регистрация: {user.created_at:%Y-%m-%d}',
        f'• Последняя активность: {_time_ago(user.last_activity_at)}',
        f'• Дней с регистрации: {days_registered}',
    ]

    lines.append('')
    if sub is None:
        lines.append('<b>Подписка:</b> нет')
    else:
        traffic_limit = 'безлимит' if sub.traffic_limit_gb == 0 else f'{sub.traffic_limit_gb} ГБ'
        lines.extend(
            [
                '<b>Подписка:</b>',
                f'• Статус: {sub.status}',
                f'• До: {sub.end_date:%Y-%m-%d %H:%M}',
                f'• Трафик: {sub.traffic_used_gb:.1f} / {traffic_limit}',
                f'• Устройства: лимит {sub.device_limit}',
            ]
        )

    if user.blocked_bot:
        lines.append('\n⚠️ Пользователь заблокировал бота — сообщения ему не доставляются.')

    return '\n'.join(lines)


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


@router.callback_query(F.data.startswith(CB_USER_BALANCE))
async def cb_user_balance(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target_id = int(callback.data[len(CB_USER_BALANCE):])
    await state.set_state(AdminUserStates.awaiting_balance_amount)
    await state.update_data(target_user_id=target_id)
    await _answer_or_edit(
        callback,
        '💰 Введите сумму в рублях (можно отрицательную — чтобы списать):',
        _back_keyboard(f'{CB_USER_CARD}{target_id}'),
    )
    await callback.answer()


@router.message(AdminUserStates.awaiting_balance_amount, F.text)
async def on_admin_balance_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    target = await db.get(User, data.get('target_user_id'))
    if target is None:
        await state.clear()
        return
    try:
        rub = float(message.text.replace(',', '.').replace('+', ''))
        kopeks = round(rub * 100)
        if kopeks == 0:
            raise ValueError
    except ValueError:
        await message.answer('Некорректная сумма. Введите ненулевое число, например 100 или -50.')
        return

    target.balance_kopeks = max(0, target.balance_kopeks + kopeks)
    db.add(
        Transaction(
            user_id=target.id,
            type='topup' if kopeks > 0 else 'refund',
            amount_kopeks=abs(kopeks),
            status='completed',
            description='Начислено администратором' if kopeks > 0 else 'Списано администратором',
        )
    )
    await db.flush()
    await state.clear()
    await notify_balance_changed(
        message.bot,
        telegram_id=target.telegram_id,
        amount_kopeks=kopeks,
        new_balance_kopeks=target.balance_kopeks,
    )
    await message.answer(
        f'✅ Баланс обновлён: {target.balance_kopeks / 100:.2f} ₽', reply_markup=_back_keyboard(f'{CB_USER_CARD}{target.id}')
    )


@router.callback_query(F.data.startswith(CB_USER_MESSAGE))
async def cb_user_message(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target_id = int(callback.data[len(CB_USER_MESSAGE):])
    await state.set_state(AdminUserStates.awaiting_message_text)
    await state.update_data(target_user_id=target_id)
    await _answer_or_edit(callback, '✉️ Введите текст сообщения для пользователя:', _back_keyboard(f'{CB_USER_CARD}{target_id}'))
    await callback.answer()


@router.message(AdminUserStates.awaiting_message_text, F.text)
async def on_admin_message_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    target = await db.get(User, data.get('target_user_id'))
    await state.clear()
    if target is None:
        return

    try:
        await message.bot.send_message(target.telegram_id, f'📩 Сообщение от администрации:\n\n{message.text}')
        result_text = '✅ Сообщение отправлено.'
    except TelegramForbiddenError:
        target.blocked_bot = True
        await db.flush()
        result_text = '⚠️ Не удалось отправить — пользователь заблокировал бота.'
    except Exception:
        logger.exception('Не удалось отправить сообщение пользователю %s', target.telegram_id)
        result_text = '⚠️ Не удалось отправить сообщение.'

    await message.answer(result_text, reply_markup=_back_keyboard(f'{CB_USER_CARD}{target.id}'))


@router.callback_query(F.data.startswith(CB_USER_REFERRALS))
async def cb_user_referrals(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target_id = int(callback.data[len(CB_USER_REFERRALS):])
    target = await db.get(User, target_id)
    if target is None:
        await callback.answer('Пользователь не найден', show_alert=True)
        return

    from app.database.models import ReferralEarning

    invited_count = (
        await db.execute(select(func.count(User.id)).where(User.referred_by_id == target.id))
    ).scalar_one()
    earned = (
        await db.execute(
            select(func.coalesce(func.sum(ReferralEarning.amount_kopeks), 0)).where(
                ReferralEarning.user_id == target.id
            )
        )
    ).scalar_one()
    text = (
        f'🤝 <b>Рефералы пользователя {target.telegram_id}</b>\n\n'
        f'Приглашено: {invited_count}\n'
        f'Заработано: {earned / 100:.2f} ₽'
    )
    await _answer_or_edit(callback, text, _back_keyboard(f'{CB_USER_CARD}{target_id}'))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_USER_TRANSACTIONS))
async def cb_user_transactions(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target_id = int(callback.data[len(CB_USER_TRANSACTIONS):])
    result = await db.execute(
        select(Transaction).where(Transaction.user_id == target_id).order_by(Transaction.created_at.desc()).limit(15)
    )
    transactions = result.scalars().all()
    if not transactions:
        text = '📋 Транзакций нет.'
    else:
        lines = ['📋 <b>Последние транзакции</b>', '']
        for t in transactions:
            sign = '+' if t.type in ('topup', 'referral_reward', 'refund', 'gift') else '-'
            lines.append(f'{t.created_at:%Y-%m-%d %H:%M} · {t.type} · {sign}{t.amount_kopeks / 100:.2f} ₽ · {t.status}')
        text = '\n'.join(lines)
    await _answer_or_edit(callback, text, _back_keyboard(f'{CB_USER_CARD}{target_id}'))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_USER_DELETE) & ~F.data.startswith(CB_USER_DELETE_YES))
async def cb_user_delete_confirm(callback: CallbackQuery, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target_id = int(callback.data[len(CB_USER_DELETE):])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='✅ Да, удалить', callback_data=f'{CB_USER_DELETE_YES}{target_id}'),
                InlineKeyboardButton(text='❌ Отмена', callback_data=f'{CB_USER_CARD}{target_id}'),
            ]
        ]
    )
    await _answer_or_edit(
        callback,
        'Удалить пользователя? Это необратимо сотрёт логин из системы: аккаунт блокируется '
        'и обезличивается (username очищается). Финансовая история и рефералы сохраняются '
        'для целостности данных — полное физическое удаление строки не выполняется '
        '(риск осиротевших записей, см. диалог).',
        kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CB_USER_DELETE_YES))
async def cb_user_delete_yes(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target_id = int(callback.data[len(CB_USER_DELETE_YES):])
    target = await db.get(User, target_id)
    if target is not None:
        target.is_blocked = True
        target.username = None
        await db.flush()
    await callback.answer('Пользователь удалён (обезличен)')
    await _answer_or_edit(callback, '✅ Готово.', _back_keyboard(CB_USERS_MENU))


# --- Партнёрка (реферальная программа — топ рефереров) ---


@router.callback_query(F.data == CB_PARTNERS_MENU)
async def cb_partners_menu(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return

    from app.database.models import ReferralEarning

    total_paid = (
        await db.execute(select(func.coalesce(func.sum(ReferralEarning.amount_kopeks), 0)))
    ).scalar_one()
    total_referred = (
        await db.execute(select(func.count(User.id)).where(User.referred_by_id.is_not(None)))
    ).scalar_one()

    top_result = await db.execute(
        select(User.telegram_id, User.username, func.sum(ReferralEarning.amount_kopeks).label('earned'))
        .join(ReferralEarning, ReferralEarning.user_id == User.id)
        .group_by(User.id)
        .order_by(func.sum(ReferralEarning.amount_kopeks).desc())
        .limit(10)
    )
    top_rows = top_result.all()

    lines = [
        '🤝 <b>Партнёрская программа</b>',
        '',
        f'Приглашённых всего: {total_referred}',
        f'Выплачено рефералам: {total_paid / 100:.2f} ₽',
        f'Процент начисления: {settings.REFERRAL_PERCENT}% с каждой оплаты приглашённого',
        '',
        '<b>Топ-10 по заработку:</b>',
    ]
    if not top_rows:
        lines.append('пока никто ничего не заработал')
    else:
        for i, (tg_id, username, earned) in enumerate(top_rows, start=1):
            lines.append(f'{i}. @{username or tg_id} — {earned / 100:.2f} ₽')

    await _answer_or_edit(callback, '\n'.join(lines), _back_keyboard(CB_USERS_ROOT))
    await callback.answer()


# --- Подписки (все подписки, отдельно от карточек пользователей) ---


@router.callback_query(F.data.startswith(CB_SUBS_MENU))
async def cb_subs_menu(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    page = int(callback.data[len(CB_SUBS_MENU):])

    total = (await db.execute(select(func.count(Subscription.id)))).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    result = await db.execute(
        select(Subscription, User)
        .join(User, User.id == Subscription.user_id)
        .order_by(Subscription.end_date.desc())
        .limit(PAGE_SIZE)
        .offset(page * PAGE_SIZE)
    )
    rows_data = result.all()

    rows = []
    for sub, user in rows_data:
        icon = '💎' if sub.status == 'active' else '⛔'
        label = user.username or f'id{user.telegram_id}'
        rows.append(
            [
                InlineKeyboardButton(
                    text=f'{icon} {label} — до {sub.end_date:%d.%m.%Y}', callback_data=f'{CB_USER_CARD}{user.id}'
                )
            ]
        )
    if rows:
        rows.append(_pagination_row(CB_SUBS_MENU, page, total_pages))
    rows.append([_back_button(CB_USERS_ROOT)])

    text = f'📱 <b>Подписки</b> (стр. {page + 1}/{total_pages}, всего: {total})' if rows_data else 'Подписок пока нет.'
    await _answer_or_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


# --- Тарифы (мультитариф — см. диалог: "Онлайн"/"Семейный") ---

CB_TARIFF_CARD = 'admin:tariff:card:'  # + tariff_id


async def _get_all_tariffs(db: AsyncSession) -> list[Tariff]:
    result = await db.execute(select(Tariff).order_by(Tariff.id))
    return list(result.scalars().all())


def _tariffs_list_keyboard(tariffs: list[Tariff]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f'{"✅" if t.is_active else "🚫"} {t.name}', callback_data=f'{CB_TARIFF_CARD}{t.id}'
            )
        ]
        for t in tariffs
    ]
    rows.append([_back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tariff_keyboard(tariff: Tariff) -> InlineKeyboardMarkup:
    trial_toggle_text = '🎁 Выключить триал' if tariff.trial_enabled else '🎁 Включить триал'
    rows = [
        [InlineKeyboardButton(text='✏️ Название', callback_data=f'{CB_TARIFF_EDIT_NAME}:{tariff.id}')],
        [InlineKeyboardButton(text='✏️ Лимит трафика', callback_data=f'{CB_TARIFF_EDIT_TRAFFIC}:{tariff.id}')],
        [InlineKeyboardButton(text='✏️ Лимит устройств', callback_data=f'{CB_TARIFF_EDIT_DEVICES}:{tariff.id}')],
        [InlineKeyboardButton(text=trial_toggle_text, callback_data=f'{CB_TARIFF_TOGGLE_TRIAL}{tariff.id}')],
        [InlineKeyboardButton(text='✏️ Дней триала', callback_data=f'{CB_TARIFF_EDIT_TRIAL_DAYS}:{tariff.id}')],
    ]
    for period in sorted(tariff.period_prices_kopeks.keys(), key=int):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f'✏️ Цена за {period} дн.', callback_data=f'{CB_TARIFF_EDIT_PERIOD}{period}:{tariff.id}'
                )
            ]
        )
    rows.append([_back_button(f'{CB_ADMIN_TARIFF}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tariff_text(tariff: Tariff) -> str:
    traffic = 'безлимит' if tariff.traffic_limit_gb == 0 else f'{tariff.traffic_limit_gb} ГБ'
    trial = f'включён, {tariff.trial_period_days} дн.' if tariff.trial_enabled else 'выключен'
    lines = [
        f'<b>Тариф: {tariff.name}</b>',
        f'Лимит трафика: {traffic}',
        f'Лимит устройств: {tariff.device_limit}',
        f'Триал: {trial}',
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
    tariffs = await _get_all_tariffs(db)
    if not tariffs:
        await _answer_or_edit(callback, 'Тарифов пока нет.', _back_keyboard())
        await callback.answer()
        return
    if len(tariffs) == 1:
        await _answer_or_edit(callback, _tariff_text(tariffs[0]), _tariff_keyboard(tariffs[0]))
        await callback.answer()
        return
    await _answer_or_edit(callback, '💳 <b>Тарифы</b>', _tariffs_list_keyboard(tariffs))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_TARIFF_CARD))
async def cb_tariff_card(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    tariff_id = int(callback.data[len(CB_TARIFF_CARD):])
    tariff = await db.get(Tariff, tariff_id)
    if tariff is None:
        await callback.answer('Тариф не найден', show_alert=True)
        return
    await _answer_or_edit(callback, _tariff_text(tariff), _tariff_keyboard(tariff))
    await callback.answer()


@router.callback_query(F.data.startswith(f'{CB_TARIFF_EDIT_NAME}:'))
async def cb_tariff_edit_name(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    tariff_id = int(callback.data.rsplit(':', 1)[1])
    await state.update_data(tariff_field='name', tariff_id=tariff_id)
    await state.set_state(AdminTariffStates.entering_name)
    await _answer_or_edit(callback, '✏️ Введите новое название тарифа:', _back_keyboard(f'{CB_TARIFF_CARD}{tariff_id}'))
    await callback.answer()


@router.message(AdminTariffStates.entering_name, F.text)
async def on_admin_tariff_name_input(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    name = message.text.strip()
    if not (2 <= len(name) <= 64):
        await message.answer('Название должно быть от 2 до 64 символов.')
        return

    data = await state.get_data()
    tariff = await db.get(Tariff, data.get('tariff_id'))
    if tariff is None:
        await state.clear()
        return
    tariff.name = name
    await db.flush()
    await state.clear()
    await message.answer(f'✅ Название обновлено: {name}', reply_markup=_back_keyboard(f'{CB_TARIFF_CARD}{tariff.id}'))


@router.callback_query(F.data.startswith(f'{CB_TARIFF_EDIT_TRAFFIC}:'))
async def cb_tariff_edit_traffic(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    tariff_id = int(callback.data.rsplit(':', 1)[1])
    await state.set_state(AdminTariffStates.entering_prices)  # переиспользуем как "ждём число"
    await state.update_data(tariff_field='traffic', tariff_id=tariff_id)
    await _answer_or_edit(
        callback, '✏️ Введите лимит трафика в ГБ (0 = безлимит):', _back_keyboard(f'{CB_TARIFF_CARD}{tariff_id}')
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f'{CB_TARIFF_EDIT_DEVICES}:'))
async def cb_tariff_edit_devices(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    tariff_id = int(callback.data.rsplit(':', 1)[1])
    await state.set_state(AdminTariffStates.entering_prices)
    await state.update_data(tariff_field='devices', tariff_id=tariff_id)
    await _answer_or_edit(callback, '✏️ Введите лимит устройств:', _back_keyboard(f'{CB_TARIFF_CARD}{tariff_id}'))
    await callback.answer()


@router.callback_query(F.data.startswith(CB_TARIFF_TOGGLE_TRIAL))
async def cb_tariff_toggle_trial(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    tariff_id = int(callback.data[len(CB_TARIFF_TOGGLE_TRIAL):])
    tariff = await db.get(Tariff, tariff_id)
    if tariff is None:
        await callback.answer('Тариф не найден', show_alert=True)
        return
    tariff.trial_enabled = not tariff.trial_enabled
    await db.flush()
    await _answer_or_edit(callback, _tariff_text(tariff), _tariff_keyboard(tariff))
    await callback.answer('Обновлено')


@router.callback_query(F.data.startswith(f'{CB_TARIFF_EDIT_TRIAL_DAYS}:'))
async def cb_tariff_edit_trial_days(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    tariff_id = int(callback.data.rsplit(':', 1)[1])
    await state.set_state(AdminTariffStates.entering_prices)
    await state.update_data(tariff_field='trial_days', tariff_id=tariff_id)
    await _answer_or_edit(
        callback, '✏️ Введите длительность триала в днях:', _back_keyboard(f'{CB_TARIFF_CARD}{tariff_id}')
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CB_TARIFF_EDIT_PERIOD))
async def cb_tariff_edit_period(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    period, tariff_id_str = callback.data[len(CB_TARIFF_EDIT_PERIOD):].rsplit(':', 1)
    tariff_id = int(tariff_id_str)
    await state.update_data(tariff_field='price', tariff_period=period, tariff_id=tariff_id)
    await state.set_state(AdminTariffStates.entering_prices)
    await _answer_or_edit(
        callback,
        f'✏️ Введите новую цену для периода {period} дней в рублях (например 299.00):',
        _back_keyboard(f'{CB_TARIFF_CARD}{tariff_id}'),
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

    tariff = await db.get(Tariff, data.get('tariff_id'))
    if tariff is None:
        await message.answer('Тариф не найден.')
        await state.clear()
        return
    back_kb = _back_keyboard(f'{CB_TARIFF_CARD}{tariff.id}')

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
    elif field == 'trial_days':
        try:
            value = int(message.text.strip())
            if value <= 0:
                raise ValueError
        except ValueError:
            await message.answer('Некорректное число. Введите целое число > 0.')
            return
        tariff.trial_period_days = value
        result_text = f'✅ Длительность триала обновлена: {value} дн.'
    else:
        await state.clear()
        return

    await db.flush()
    await state.clear()
    await message.answer(result_text, reply_markup=back_kb)


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
#
# Перенесено из app/handlers/admin/messages.py оригинального Bedolaga (см. диалог
# "берём как есть"): выбор аудитории с live-счётчиком -> текст (HTML, ≤4000) ->
# медиа (фото/видео/документ, опционально) -> предпросмотр медиа -> конструктор
# inline-кнопок -> финальный предпросмотр -> отправка батчами с ретраями на
# FloodWait и живым прогресс-баром -> история рассылок.
#
# Отличия от оригинала (см. диалог про масштаб):
#  - нет сегментов "триал"/"активна 0 ГБ" — у нас нет триальных подписок вообще;
#  - "По тарифу" использует наш реальный список тарифов (Онлайн/Семейный);
#  - кнопка "Пополнить баланс" убрана — у нас нет отдельного flow пополнения без
#    покупки подписки/промокода, добавлять фиктивную кнопку в никуда не стали;
#  - подсчёт и реальная выборка получателей — ОДНА функция (см. _broadcast_target_users),
#    а не отдельные COUNT/SELECT как в оригинале — их же комментарий в оригинале
#    прямо предупреждает, что раздельные версии рискуют разъехаться числом; здесь
#    так разъехаться в принципе не может;
#  - наша сессия БД живёт на весь хендлер (AuthMiddleware), поэтому не нужен
#    трюк оригинала с извлечением скаляров "на случай смерти соединения".

BROADCAST_TARGETS: dict[str, str] = {
    'all': '👥 Всем',
    'active': '📱 С подпиской',
    'no_sub': '❌ Без подписки',
    'expiring': '⏰ Истекающие',
    'expired': '🔚 Истёкшие',
}

CB_BROADCAST_TARGET = 'broadcast:target:'  # + ключ из BROADCAST_TARGETS, либо tariff:<id>
CB_BROADCAST_TARGET_TARIFF_MENU = 'broadcast:target_tariff_menu'

CB_BROADCAST_MEDIA = 'broadcast:media:'  # + photo|video|document|skip
CB_BROADCAST_MEDIA_CONFIRM = 'broadcast:media_confirm'
CB_BROADCAST_MEDIA_CHANGE = 'broadcast:media_change'

CB_BROADCAST_BTN_TOGGLE = 'broadcast:btn:'  # + ключ кнопки
CB_BROADCAST_BTN_CONTINUE = 'broadcast:btn_continue'

CB_BROADCAST_HISTORY = 'broadcast:history:'  # + page

# Кнопки-конструктор для тела рассылки — используют РЕАЛЬНЫЕ callback_data других
# модулей (main_menu.py/referral.py/promocode.py/support.py): при клике по кнопке
# в разосланном сообщении сработает штатный хендлер соответствующего модуля,
# это не заглушки. 'balance'/'connect' у оригинала — не переносим, см. комментарий выше.
BROADCAST_BUTTONS: dict[str, dict[str, str]] = {
    'subscription': {'text': '📱 Моя подписка', 'callback': CB_SUBSCRIPTION_MY},
    'renew': {'text': '💎 Продлить подписку', 'callback': CB_SUBSCRIPTION_RENEW},
    'referrals': {'text': '🤝 Партнёрка', 'callback': CB_REFERRAL_MENU},
    'promocode': {'text': '🎫 Промокод', 'callback': CB_PROMO_ENTER},
    'support': {'text': '🛠️ Техподдержка', 'callback': CB_SUPPORT_MENU},
    'home': {'text': '🏠 На главную', 'callback': CB_MENU_MAIN},
}
BROADCAST_BUTTON_ROWS: tuple[tuple[str, ...], ...] = (
    ('subscription', 'renew'),
    ('referrals', 'promocode'),
    ('support',),
    ('home',),
)
DEFAULT_BROADCAST_BUTTONS = ('home',)

_BROADCAST_MEDIA_LABELS = {'photo': 'Фотография', 'video': 'Видео', 'document': 'Документ'}


async def _broadcast_target_users(db: AsyncSession, target: str) -> list[User]:
    """Единая функция и для счётчика (len(...)), и для реальной выборки —
    см. комментарий в начале секции про то, почему это осознанно не два запроса."""
    now = datetime.now(timezone.utc)

    if target == 'all':
        stmt = select(User)
    elif target == 'active':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(Subscription.status == 'active')
    elif target == 'no_sub':
        has_active = (
            select(Subscription.id)
            .where(Subscription.user_id == User.id, Subscription.status == 'active')
            .correlate(User)
            .exists()
        )
        stmt = select(User).where(~has_active)
    elif target == 'expiring':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(
            Subscription.status == 'active',
            Subscription.end_date <= now + timedelta(days=3),
            Subscription.end_date > now,
        )
    elif target == 'expired':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(Subscription.status == 'expired')
    elif target.startswith('tariff:'):
        tariff_id = int(target.split(':', 1)[1])
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(
            Subscription.status == 'active', Subscription.tariff_id == tariff_id
        )
    else:
        return []

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def _broadcast_target_display_name(db: AsyncSession, target: str) -> str:
    if target in BROADCAST_TARGETS:
        return BROADCAST_TARGETS[target]
    if target.startswith('tariff:'):
        tariff = await db.get(Tariff, int(target.split(':', 1)[1]))
        return f'Тариф «{tariff.name}»' if tariff else 'Тариф (удалён)'
    return target


def _broadcast_target_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f'{CB_BROADCAST_TARGET}{key}')]
        for key, label in BROADCAST_TARGETS.items()
    ]
    rows.append([InlineKeyboardButton(text='📦 По тарифу', callback_data=CB_BROADCAST_TARGET_TARIFF_MENU)])
    rows.append([_back_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _broadcast_media_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='📷 Добавить фото', callback_data=f'{CB_BROADCAST_MEDIA}photo'),
                InlineKeyboardButton(text='🎥 Добавить видео', callback_data=f'{CB_BROADCAST_MEDIA}video'),
            ],
            [
                InlineKeyboardButton(text='📄 Добавить документ', callback_data=f'{CB_BROADCAST_MEDIA}document'),
                InlineKeyboardButton(text='⏭️ Пропустить медиа', callback_data=f'{CB_BROADCAST_MEDIA}skip'),
            ],
            [InlineKeyboardButton(text='❌ Отмена', callback_data=CB_ADMIN_BROADCAST)],
        ]
    )


def _broadcast_media_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='✅ Продолжить', callback_data=CB_BROADCAST_MEDIA_CONFIRM),
                InlineKeyboardButton(text='🔄 Заменить', callback_data=CB_BROADCAST_MEDIA_CHANGE),
            ]
        ]
    )


def _broadcast_buttons_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row_keys in BROADCAST_BUTTON_ROWS:
        row = []
        for key in row_keys:
            mark = '✅' if key in selected else '⬜'
            row.append(
                InlineKeyboardButton(
                    text=f'{mark} {BROADCAST_BUTTONS[key]["text"]}', callback_data=f'{CB_BROADCAST_BTN_TOGGLE}{key}'
                )
            )
        rows.append(row)
    rows.append([InlineKeyboardButton(text='➡️ Продолжить', callback_data=CB_BROADCAST_BTN_CONTINUE)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _broadcast_result_keyboard(selected: list[str]) -> InlineKeyboardMarkup | None:
    ordered_keys = [k for row in BROADCAST_BUTTON_ROWS for k in row if k in selected]
    if not ordered_keys:
        return None
    rows = [[InlineKeyboardButton(text=BROADCAST_BUTTONS[k]['text'], callback_data=BROADCAST_BUTTONS[k]['callback'])] for k in ordered_keys]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == CB_ADMIN_BROADCAST)
async def cb_admin_broadcast(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    await state.clear()
    kb = _broadcast_target_keyboard()
    kb.inline_keyboard.append([InlineKeyboardButton(text='📋 История рассылок', callback_data=f'{CB_BROADCAST_HISTORY}0')])
    await state.set_state(AdminBroadcastStates.choosing_target)
    await _answer_or_edit(callback, '🎯 <b>Выбор целевой аудитории</b>\n\nВыберите категорию пользователей для рассылки:', kb)
    await callback.answer()


@router.callback_query(F.data == CB_BROADCAST_TARGET_TARIFF_MENU)
async def cb_broadcast_target_tariff_menu(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    tariffs = await get_active_tariffs(db)
    if not tariffs:
        await callback.answer('Нет доступных тарифов', show_alert=True)
        return
    rows = []
    for t in tariffs:
        count = len(await _broadcast_target_users(db, f'tariff:{t.id}'))
        rows.append([InlineKeyboardButton(text=f'{t.name} ({count} чел.)', callback_data=f'{CB_BROADCAST_TARGET}tariff:{t.id}')])
    rows.append([_back_button(CB_ADMIN_BROADCAST)])
    await _answer_or_edit(callback, '📦 <b>Рассылка по тарифу</b>\n\nВыберите тариф:', InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(AdminBroadcastStates.choosing_target, F.data.startswith(CB_BROADCAST_TARGET))
async def cb_broadcast_pick_target(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    target = callback.data[len(CB_BROADCAST_TARGET):]
    users = await _broadcast_target_users(db, target)
    target_name = await _broadcast_target_display_name(db, target)

    await state.update_data(broadcast_target=target)
    await state.set_state(AdminBroadcastStates.entering_text)
    await _answer_or_edit(
        callback,
        f'📨 <b>Создание рассылки</b>\n\n🎯 <b>Аудитория:</b> {target_name}\n👥 <b>Получателей:</b> {len(users)}\n\n'
        f'Введите текст сообщения (поддерживается HTML, до 4000 символов):',
        _back_keyboard(CB_ADMIN_BROADCAST),
    )
    await callback.answer()


@router.message(AdminBroadcastStates.entering_text, F.text)
async def on_admin_broadcast_text(message: Message, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    if len(message.text) > 4000:
        await message.answer('❌ Сообщение слишком длинное (максимум 4000 символов)')
        return
    await state.update_data(broadcast_text=message.text)
    await state.set_state(AdminBroadcastStates.choosing_media)
    await message.answer(
        '🖼️ <b>Добавление медиафайла</b>\n\nМожно добавить фото, видео или документ — или пропустить этот шаг.',
        reply_markup=_broadcast_media_keyboard(),
    )


@router.callback_query(AdminBroadcastStates.choosing_media, F.data.startswith(CB_BROADCAST_MEDIA))
async def cb_broadcast_media_pick(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    choice = callback.data[len(CB_BROADCAST_MEDIA):]
    if choice == 'skip':
        await state.update_data(has_media=False)
        await _show_broadcast_button_selector(callback.message, state, use_edit=True, callback=callback)
        await callback.answer()
        return

    await state.update_data(media_type=choice)
    await state.set_state(AdminBroadcastStates.awaiting_media)
    label = _BROADCAST_MEDIA_LABELS.get(choice, 'файл')
    await _answer_or_edit(
        callback, f'Отправьте {label.lower()} для рассылки:', _back_keyboard(CB_ADMIN_BROADCAST)
    )
    await callback.answer()


@router.message(AdminBroadcastStates.awaiting_media)
async def on_admin_broadcast_media(message: Message, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    expected = data.get('media_type')

    media_file_id = None
    if message.photo and expected == 'photo':
        media_file_id = message.photo[-1].file_id
    elif message.video and expected == 'video':
        media_file_id = message.video.file_id
    elif message.document and expected == 'document':
        media_file_id = message.document.file_id
    else:
        await message.answer(f'❌ Пришлите именно {_BROADCAST_MEDIA_LABELS.get(expected, "файл").lower()}, как указано выше.')
        return

    await state.update_data(has_media=True, media_file_id=media_file_id)

    preview_text = f'🖼️ <b>Медиафайл добавлен</b>\n\n📎 Тип: {_BROADCAST_MEDIA_LABELS.get(expected, expected)}\n\nЧто дальше?'
    if expected == 'photo':
        await message.answer_photo(media_file_id, caption=preview_text, reply_markup=_broadcast_media_confirm_keyboard())
    else:
        await message.answer(preview_text, reply_markup=_broadcast_media_confirm_keyboard())


async def _show_broadcast_button_selector(message: Message, state: FSMContext, *, use_edit: bool, callback: CallbackQuery | None = None) -> None:
    data = await state.get_data()
    selected = data.get('selected_buttons')
    if selected is None:
        selected = list(DEFAULT_BROADCAST_BUTTONS)
        await state.update_data(selected_buttons=selected)

    text = (
        '📘 <b>Выбор дополнительных кнопок</b>\n\nВыберите кнопки, которые будут добавлены к сообщению рассылки:\n\n'
        '📱 <b>Моя подписка</b> / 💎 <b>Продлить</b> — экран подписки\n'
        '🤝 <b>Партнёрка</b> — реферальная программа\n'
        '🎫 <b>Промокод</b> — форма ввода промокода\n'
        '🛠️ <b>Техподдержка</b> — связь с поддержкой\n\n'
        '🏠 <b>На главную</b> включена по умолчанию.\n\nВыберите нужные и нажмите «Продолжить»:'
    )
    keyboard = _broadcast_buttons_keyboard(selected)
    await state.set_state(AdminBroadcastStates.choosing_buttons)

    if use_edit and callback is not None:
        await _answer_or_edit(callback, text, keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == CB_BROADCAST_MEDIA_CONFIRM)
async def cb_broadcast_media_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_broadcast_button_selector(callback.message, state, use_edit=False)
    await callback.answer()


@router.callback_query(F.data == CB_BROADCAST_MEDIA_CHANGE)
async def cb_broadcast_media_change(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminBroadcastStates.choosing_media)
    await callback.message.answer('🖼️ Выберите новый тип медиа:', reply_markup=_broadcast_media_keyboard())
    await callback.answer()


@router.callback_query(AdminBroadcastStates.choosing_buttons, F.data.startswith(CB_BROADCAST_BTN_TOGGLE))
async def cb_broadcast_btn_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data[len(CB_BROADCAST_BTN_TOGGLE):]
    data = await state.get_data()
    selected = list(data.get('selected_buttons') or DEFAULT_BROADCAST_BUTTONS)
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(selected_buttons=selected)
    await callback.message.edit_reply_markup(reply_markup=_broadcast_buttons_keyboard(selected))
    await callback.answer()


@router.callback_query(AdminBroadcastStates.choosing_buttons, F.data == CB_BROADCAST_BTN_CONTINUE)
async def cb_broadcast_btn_continue(callback: CallbackQuery, db: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    target = data['broadcast_target']
    text = data.get('broadcast_text')
    selected = data.get('selected_buttons') or list(DEFAULT_BROADCAST_BUTTONS)
    has_media = data.get('has_media', False)
    media_type = data.get('media_type')

    users = await _broadcast_target_users(db, target)
    target_name = await _broadcast_target_display_name(db, target)

    media_info = f'\n🖼️ <b>Медиафайл:</b> {_BROADCAST_MEDIA_LABELS.get(media_type, media_type)}' if has_media else ''
    ordered_keys = [k for row in BROADCAST_BUTTON_ROWS for k in row if k in selected]
    buttons_info = ', '.join(BROADCAST_BUTTONS[k]['text'] for k in ordered_keys) or 'отсутствуют'

    preview = (
        f'📨 <b>Предварительный просмотр рассылки</b>\n\n'
        f'🎯 <b>Аудитория:</b> {target_name}\n👥 <b>Получателей:</b> {len(users)}\n\n'
        f'📝 <b>Сообщение:</b>\n{text}{media_info}\n\n📘 <b>Кнопки:</b> {buttons_info}\n\nПодтвердить отправку?'
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='✅ Отправить', callback_data=CB_BROADCAST_CONFIRM),
                InlineKeyboardButton(text='❌ Отмена', callback_data=CB_BROADCAST_CANCEL),
            ]
        ]
    )
    await state.set_state(AdminBroadcastStates.confirming)
    await _answer_or_edit(callback, preview, kb)
    await callback.answer()


@router.callback_query(AdminBroadcastStates.confirming, F.data == CB_BROADCAST_CANCEL)
async def cb_admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _answer_or_edit(callback, 'Рассылка отменена.', _back_keyboard())
    await callback.answer()


@router.callback_query(AdminBroadcastStates.confirming, F.data == CB_BROADCAST_CONFIRM)
async def cb_admin_broadcast_confirm(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    data = await state.get_data()
    target = data['broadcast_target']
    text = data.get('broadcast_text')
    selected = data.get('selected_buttons') or list(DEFAULT_BROADCAST_BUTTONS)
    has_media = data.get('has_media', False)
    media_type = data.get('media_type')
    media_file_id = data.get('media_file_id')
    await state.clear()
    if not text:
        await callback.answer()
        return

    await callback.answer('Рассылка запущена…')
    await _answer_or_edit(callback, '📨 Подготовка рассылки…', None)

    users = await _broadcast_target_users(db, target)
    recipient_ids = [u.telegram_id for u in users]

    history = BroadcastHistory(
        target_type=target,
        message_text=text,
        has_media=has_media,
        media_type=media_type,
        media_file_id=media_file_id,
        total_count=len(recipient_ids),
        admin_id=db_user.id,
        admin_name=db_user.username or str(db_user.telegram_id),
        status='in_progress',
    )
    db.add(history)
    await db.commit()

    reply_markup = _broadcast_result_keyboard(selected)

    # Батчи по 25 с паузой 1с — те же параметры, что у Bedolaga (запас от лимита
    # Telegram ~30 msg/sec для бота), с ретраем на FloodWait.
    BATCH_SIZE = 25
    BATCH_DELAY = 1.0
    MAX_RETRIES = 3
    flood_wait_until = 0.0

    async def send_one(telegram_id: int) -> str:
        nonlocal flood_wait_until
        for attempt in range(MAX_RETRIES):
            now = asyncio.get_event_loop().time()
            if flood_wait_until > now:
                await asyncio.sleep(flood_wait_until - now)
            try:
                if has_media and media_file_id:
                    send_method = {
                        'photo': callback.bot.send_photo,
                        'video': callback.bot.send_video,
                        'document': callback.bot.send_document,
                    }[media_type]
                    kwarg = {'photo': 'photo', 'video': 'video', 'document': 'document'}[media_type]
                    if len(text) <= 1024:
                        await send_method(chat_id=telegram_id, **{kwarg: media_file_id}, caption=text, reply_markup=reply_markup)
                    else:
                        await send_method(chat_id=telegram_id, **{kwarg: media_file_id})
                        await callback.bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                else:
                    await callback.bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                return 'sent'
            except TelegramRetryAfter as exc:
                flood_wait_until = asyncio.get_event_loop().time() + exc.retry_after + 1
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                return 'blocked'
            except Exception:
                logger.debug('Ошибка отправки рассылки %s (попытка %s)', telegram_id, attempt + 1, exc_info=True)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return 'failed'

    sent_count = failed_count = blocked_count = 0
    blocked_ids: list[int] = []
    last_progress = 0.0
    progress_message = callback.message

    for batch_idx, i in enumerate(range(0, len(recipient_ids), BATCH_SIZE)):
        batch = recipient_ids[i : i + BATCH_SIZE]
        results = await asyncio.gather(*[send_one(tid) for tid in batch], return_exceptions=True)
        for idx, result in enumerate(results):
            if result == 'sent':
                sent_count += 1
            elif result == 'blocked':
                blocked_count += 1
                blocked_ids.append(batch[idx])
            else:
                failed_count += 1

        now = asyncio.get_event_loop().time()
        if now - last_progress >= 5.0:
            last_progress = now
            processed = sent_count + failed_count + blocked_count
            percent = round(processed / len(recipient_ids) * 100, 1) if recipient_ids else 100
            bar = '█' * int(20 * processed / max(len(recipient_ids), 1)) + '░' * (20 - int(20 * processed / max(len(recipient_ids), 1)))
            try:
                await progress_message.edit_text(
                    f'📨 <b>Рассылка в процессе...</b>\n\n[{bar}] {percent}%\n\n'
                    f'Отправлено: {sent_count} · Заблокировали: {blocked_count} · Ошибок: {failed_count}\n'
                    f'Обработано: {processed}/{len(recipient_ids)}'
                )
            except Exception:
                pass
        await asyncio.sleep(BATCH_DELAY)

    if blocked_ids:
        await db.execute(update(User).where(User.telegram_id.in_(blocked_ids)).values(blocked_bot=True))

    history.sent_count = sent_count
    history.failed_count = failed_count
    history.blocked_count = blocked_count
    history.status = 'completed' if failed_count == 0 and blocked_count == 0 else 'partial'
    history.completed_at = datetime.now(timezone.utc)
    await db.commit()

    success_rate = round(sent_count / len(recipient_ids) * 100, 1) if recipient_ids else 0
    result_text = (
        f'✅ <b>Рассылка завершена!</b>\n\n📊 Отправлено: {sent_count}\n'
        f'🚫 Заблокировали бота: {blocked_count}\n❌ Не доставлено: {failed_count}\n'
        f'👥 Всего: {len(recipient_ids)}\n📈 Успешность: {success_rate}%'
    )
    try:
        await progress_message.edit_text(result_text, reply_markup=_back_keyboard())
    except Exception:
        await callback.message.answer(result_text, reply_markup=_back_keyboard())


@router.callback_query(F.data.startswith(CB_BROADCAST_HISTORY))
async def cb_broadcast_history(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    page = int(callback.data[len(CB_BROADCAST_HISTORY):])

    total = (await db.execute(select(func.count(BroadcastHistory.id)))).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    result = await db.execute(
        select(BroadcastHistory).order_by(BroadcastHistory.created_at.desc()).limit(PAGE_SIZE).offset(page * PAGE_SIZE)
    )
    broadcasts = result.scalars().all()

    if not broadcasts:
        text = '📋 <b>История рассылок</b>\n\nПока пусто.'
    else:
        status_emoji = {'completed': '✅', 'partial': '⚠️', 'in_progress': '⏳'}
        lines = [f'📋 <b>История рассылок</b> (стр. {page + 1}/{total_pages})', '']
        for b in broadcasts:
            preview = (b.message_text or '')[:80]
            lines.append(
                f'{status_emoji.get(b.status, "•")} {b.created_at:%d.%m.%Y %H:%M} · '
                f'{b.sent_count}/{b.total_count} доставлено · {preview}'
            )
        text = '\n'.join(lines)

    rows = []
    if broadcasts:
        rows.append(_pagination_row(CB_BROADCAST_HISTORY, page, total_pages))
    rows.append([_back_button(CB_ADMIN_BROADCAST)])
    await _answer_or_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


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
