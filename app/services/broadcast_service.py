"""Рассылка по пользователям: аудитории, кнопки-конструктор, отправка пачками с ретраями,
прогресс и отмена. Единственное место, где живёт логика отправки — бот (app/handlers/admin.py,
через run_broadcast_now — ждёт завершения) и API (app/cabinet/broadcast_routes.py, через
start_broadcast — фоновая задача) вызывают этот же код, никакого дублирования."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import AsyncSessionLocal
from app.database.models import BroadcastHistory, Subscription, Tariff, User
from app.handlers.promocode import CB_PROMO_ENTER
from app.keyboards.main_menu import CB_MENU_MAIN, CB_REFERRAL_MENU, CB_SUBSCRIPTION_MY, CB_SUBSCRIPTION_RENEW, CB_SUPPORT_MENU
from app.logging_setup import get_logger

log = get_logger(__name__)

BROADCAST_TARGETS: dict[str, str] = {
    'all': '👥 Всем',
    'active': '📱 С подпиской',
    'no_sub': '❌ Без подписки',
    'expiring': '⏰ Истекающие',
    'expired': '🔚 Истёкшие',
}

# Кнопки-конструктор для тела рассылки — используют РЕАЛЬНЫЕ callback_data других модулей
# (main_menu.py/referral.py/promocode.py/support.py): при клике по кнопке в разосланном
# сообщении сработает штатный хендлер соответствующего модуля, это не заглушки.
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
DEFAULT_BROADCAST_BUTTONS: tuple[str, ...] = ('home',)

ALLOWED_MEDIA_TYPES = frozenset({'photo', 'video', 'document'})


async def target_users(db: AsyncSession, target: str) -> list[User]:
    """Единая функция и для счётчика (len(...)), и для реальной выборки — то же решение, что
    было в handlers/admin.py, перенесено без изменения поведения (неизвестный target — []).
    now, timedelta, timezone: даты хранятся в UTC (see также app/services/time_utils.py)."""
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


async def target_display_name(db: AsyncSession, target: str) -> str:
    if target in BROADCAST_TARGETS:
        return BROADCAST_TARGETS[target]
    if target.startswith('tariff:'):
        tariff = await db.get(Tariff, int(target.split(':', 1)[1]))
        return f'Тариф «{tariff.name}»' if tariff else 'Тариф (удалён)'
    return target


def result_keyboard(selected: list[str]) -> InlineKeyboardMarkup | None:
    ordered_keys = [k for row in BROADCAST_BUTTON_ROWS for k in row if k in selected]
    if not ordered_keys:
        return None
    rows = [[InlineKeyboardButton(text=BROADCAST_BUTTONS[k]['text'], callback_data=BROADCAST_BUTTONS[k]['callback'])] for k in ordered_keys]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- отправка, прогресс, отмена -----------------------------------------------------------------

# Батчи по 25 с паузой 1с — запас от лимита Telegram ~30 msg/sec для бота, с ретраем на FloodWait
# (те же параметры, что были в handlers/admin.py до выноса).
BATCH_SIZE = 25
BATCH_DELAY = 1.0
MAX_RETRIES = 3
PROGRESS_COMMIT_INTERVAL = 5.0

ProgressCallback = Callable[[BroadcastHistory], Awaitable[None]]

# id рассылки -> флаг отмены. Один процесс, поэтому память достаточна; переживает рестарт
# не должна — см. mark_interrupted_broadcasts.
_cancel_flags: dict[int, asyncio.Event] = {}

# Сильные ссылки на фоновые задачи рассылок (start_broadcast) — без этого asyncio может собрать
# задачу как мусор посреди выполнения (см. предупреждение в документации asyncio.create_task).
_background_tasks: set[asyncio.Task] = set()


class BroadcastAlreadyRunningError(Exception):
    """Уже есть рассылка со статусом in_progress — общий Telegram-лимит один на процесс."""


class BroadcastNotFoundError(Exception):
    pass


class BroadcastNotRunningError(Exception):
    """Рассылка уже не in_progress — отменять нечего."""


@dataclass
class _PreparedBroadcast:
    history: BroadcastHistory
    recipient_ids: list[int]
    reply_markup: InlineKeyboardMarkup | None
    cancel_event: asyncio.Event


async def _prepare_broadcast(
    db: AsyncSession,
    *,
    admin: User,
    target: str,
    text: str,
    media_type: str | None,
    media_file_id: str | None,
    selected_buttons: list[str] | None,
) -> _PreparedBroadcast:
    """Общая часть для start_broadcast/run_broadcast_now: проверка «одна рассылка одновременно»,
    подсчёт получателей, создание и коммит строки истории, регистрация флага отмены — ДО того,
    как первое сообщение уйдёт получателю."""
    # Синхронная (без await) проверка in-memory реестра — закрывает TOCTOU-окно между SELECT
    # ниже и INSERT+commit этой же функции при почти одновременном втором вызове; ноль стоимости
    # (без лока и лишнего запроса). Проверку по БД оставляем — она ловит зависшую строку,
    # пережившую рестарт процесса, до отработки mark_interrupted_broadcasts.
    if _cancel_flags:
        raise BroadcastAlreadyRunningError
    running = await db.execute(select(BroadcastHistory.id).where(BroadcastHistory.status == 'in_progress').limit(1))
    if running.scalar_one_or_none() is not None:
        raise BroadcastAlreadyRunningError

    recipients = await target_users(db, target)
    recipient_ids = [u.telegram_id for u in recipients]

    history = BroadcastHistory(
        target_type=target,
        message_text=text,
        has_media=bool(media_file_id),
        media_type=media_type if media_file_id else None,
        media_file_id=media_file_id,
        total_count=len(recipient_ids),
        admin_id=admin.id,
        admin_name=admin.username or str(admin.telegram_id),
        status='in_progress',
    )
    db.add(history)
    await db.commit()
    await db.refresh(history)

    selected = selected_buttons if selected_buttons is not None else list(DEFAULT_BROADCAST_BUTTONS)
    reply_markup = result_keyboard(selected)
    cancel_event = asyncio.Event()
    _cancel_flags[history.id] = cancel_event
    log.info('broadcast_started', history_id=history.id, target=target, recipients=len(recipient_ids), admin_id=admin.id)
    return _PreparedBroadcast(history=history, recipient_ids=recipient_ids, reply_markup=reply_markup, cancel_event=cancel_event)


async def _commit_progress(
    history_id: int, *, sent: int, failed: int, blocked: int, db: AsyncSession | None = None
) -> BroadcastHistory:
    if db is not None:
        history = await db.get(BroadcastHistory, history_id)
        history.sent_count = sent
        history.failed_count = failed
        history.blocked_count = blocked
        await db.commit()
        await db.refresh(history)
        return history
    async with AsyncSessionLocal() as session:
        history = await session.get(BroadcastHistory, history_id)
        history.sent_count = sent
        history.failed_count = failed
        history.blocked_count = blocked
        await session.commit()
        await session.refresh(history)
        return history


async def _finalize(
    history_id: int, *, sent: int, failed: int, blocked: int, blocked_ids: list[int], status: str,
    db: AsyncSession | None = None,
) -> BroadcastHistory:
    if db is not None:
        if blocked_ids:
            await db.execute(update(User).where(User.telegram_id.in_(blocked_ids)).values(blocked_bot=True))
        history = await db.get(BroadcastHistory, history_id)
        history.sent_count = sent
        history.failed_count = failed
        history.blocked_count = blocked
        history.status = status
        history.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(history)
        return history
    async with AsyncSessionLocal() as session:
        if blocked_ids:
            await session.execute(update(User).where(User.telegram_id.in_(blocked_ids)).values(blocked_bot=True))
        history = await session.get(BroadcastHistory, history_id)
        history.sent_count = sent
        history.failed_count = failed
        history.blocked_count = blocked
        history.status = status
        history.completed_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(history)
        return history


async def _run(
    bot: Bot,
    history_id: int,
    recipient_ids: list[int],
    *,
    text: str,
    media_type: str | None,
    media_file_id: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    cancel_event: asyncio.Event,
    on_progress: ProgressCallback | None,
    db: AsyncSession | None = None,
) -> BroadcastHistory:
    """Батчами по BATCH_SIZE с паузой BATCH_DELAY; ретрай на flood-control; заблокировавшие
    бота помечаются blocked_bot=True. Прогресс коммитится в БД каждые PROGRESS_COMMIT_INTERVAL
    сек (не только в конце — иначе GET .../{id} не видел бы прогресс долгой рассылки)."""
    sent = failed = blocked = 0
    blocked_ids: list[int] = []
    flood_wait_until = 0.0
    cancelled = False

    async def send_one(telegram_id: int) -> str:
        nonlocal flood_wait_until
        for attempt in range(MAX_RETRIES):
            now = asyncio.get_event_loop().time()
            if flood_wait_until > now:
                await asyncio.sleep(flood_wait_until - now)
            try:
                if media_file_id:
                    send_method = {'photo': bot.send_photo, 'video': bot.send_video, 'document': bot.send_document}[media_type]
                    kwarg = {'photo': 'photo', 'video': 'video', 'document': 'document'}[media_type]
                    if len(text) <= 1024:
                        await send_method(chat_id=telegram_id, **{kwarg: media_file_id}, caption=text, reply_markup=reply_markup)
                    else:
                        await send_method(chat_id=telegram_id, **{kwarg: media_file_id})
                        await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                else:
                    await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                return 'sent'
            except TelegramRetryAfter as exc:
                flood_wait_until = asyncio.get_event_loop().time() + exc.retry_after + 1
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                return 'blocked'
            except Exception:
                log.warning('broadcast_send_failed', telegram_id=telegram_id, attempt=attempt + 1, exc_info=True)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return 'failed'

    last_commit = 0.0
    try:
        try:
            for i in range(0, len(recipient_ids), BATCH_SIZE):
                if cancel_event.is_set():
                    cancelled = True
                    break
                batch = recipient_ids[i : i + BATCH_SIZE]
                results = await asyncio.gather(*[send_one(tid) for tid in batch], return_exceptions=True)
                for idx, result in enumerate(results):
                    if result == 'sent':
                        sent += 1
                    elif result == 'blocked':
                        blocked += 1
                        blocked_ids.append(batch[idx])
                    else:
                        failed += 1

                now = asyncio.get_event_loop().time()
                if now - last_commit >= PROGRESS_COMMIT_INTERVAL:
                    last_commit = now
                    history = await _commit_progress(history_id, sent=sent, failed=failed, blocked=blocked, db=db)
                    if on_progress is not None:
                        await on_progress(history)
                await asyncio.sleep(BATCH_DELAY)

            final_status = 'cancelled' if cancelled else ('completed' if failed == 0 and blocked == 0 else 'partial')
            history = await _finalize(
                history_id, sent=sent, failed=failed, blocked=blocked, blocked_ids=blocked_ids, status=final_status, db=db
            )
            log.info('broadcast_finished', history_id=history_id, status=final_status, sent=sent, failed=failed, blocked=blocked)
            if on_progress is not None:
                await on_progress(history)
            return history
        except Exception:
            # Что угодно за пределами send_one (например, ошибка БД в _commit_progress) не должно
            # оставлять строку в status='in_progress' навсегда — иначе single-flight проверка в
            # _prepare_broadcast блокирует любые новые рассылки до рестарта процесса. На пути
            # start_broadcast (fire-and-forget) исключение из этой задачи никто не ждёт, поэтому
            # логируем его здесь же перед повторным поднятием.
            log.exception('broadcast_run_crashed', history_id=history_id)
            await _finalize(
                history_id, sent=sent, failed=failed, blocked=blocked, blocked_ids=blocked_ids, status='failed', db=db
            )
            raise
    finally:
        _cancel_flags.pop(history_id, None)


async def start_broadcast(
    db: AsyncSession,
    bot: Bot,
    *,
    admin: User,
    target: str,
    text: str,
    media_type: str | None = None,
    media_file_id: str | None = None,
    selected_buttons: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> BroadcastHistory:
    """Создаёт запись истории и запускает отправку ФОНОВОЙ задачей — не дожидается её
    завершения (для API: ответ 202 сразу, прогресс — через GET .../{id})."""
    prepared = await _prepare_broadcast(
        db, admin=admin, target=target, text=text, media_type=media_type,
        media_file_id=media_file_id, selected_buttons=selected_buttons,
    )
    task = asyncio.create_task(
        _run(
            bot, prepared.history.id, prepared.recipient_ids, text=text, media_type=media_type,
            media_file_id=media_file_id, reply_markup=prepared.reply_markup,
            cancel_event=prepared.cancel_event, on_progress=on_progress,
        ),
        name=f'broadcast-{prepared.history.id}',
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return prepared.history


async def run_broadcast_now(
    db: AsyncSession,
    bot: Bot,
    *,
    admin: User,
    target: str,
    text: str,
    media_type: str | None = None,
    media_file_id: str | None = None,
    selected_buttons: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> BroadcastHistory:
    """Как start_broadcast, но ДОЖИДАЕТСЯ отправки целиком — бот уже занимает экран прогрессом,
    синхронное ожидание не хуже прежнего инлайн-цикла."""
    prepared = await _prepare_broadcast(
        db, admin=admin, target=target, text=text, media_type=media_type,
        media_file_id=media_file_id, selected_buttons=selected_buttons,
    )
    return await _run(
        bot, prepared.history.id, prepared.recipient_ids, text=text, media_type=media_type,
        media_file_id=media_file_id, reply_markup=prepared.reply_markup,
        cancel_event=prepared.cancel_event, on_progress=on_progress, db=db,
    )


async def cancel_broadcast(db: AsyncSession, history_id: int) -> BroadcastHistory:
    """Просит отправку остановиться перед следующей пачкой — уже отправленные сообщения не
    откатываются. Работает независимо от того, кто запустил рассылку (бот или API) — флаг
    один на процесс, по id."""
    history = await db.get(BroadcastHistory, history_id)
    if history is None:
        raise BroadcastNotFoundError
    if history.status != 'in_progress':
        raise BroadcastNotRunningError
    event = _cancel_flags.get(history_id)
    if event is not None:
        event.set()
    return history


async def mark_interrupted_broadcasts() -> int:
    """При старте процесса: если он упал/перезапустился посреди рассылки, ничего не
    возобновляем — только помечаем зависшие записи interrupted, иначе они навсегда блокировали
    бы правило «одна рассылка одновременно» (см. спеку, раздел «Перезапуск процесса»)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(BroadcastHistory)
            .where(BroadcastHistory.status == 'in_progress')
            .values(status='interrupted', completed_at=datetime.now(timezone.utc))
        )
        await db.commit()
        count = result.rowcount or 0
    if count:
        log.warning('broadcast_marked_interrupted', count=count)
    return count
