"""Правки автоматических сообщений: кэш, сохранение, сброс и отправка через шаблоны.

Заводские тексты — в registry.py, правки владельца — в таблице message_templates. Любая проблема с
правками (сбой БД, отказ Telegram из-за разметки/эмодзи) не должна терять уведомление: тогда уходит
заводской текст."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.database import AsyncSessionLocal
from app.database.models import MessageTemplate
from app.logging_setup import get_logger
from app.services.message_templates.keyboards import build_keyboard
from app.services.message_templates.registry import EventDef, get_event
from app.services.message_templates.render import render_template
from app.services.message_templates.validation import validate_button_text, validate_template

log = get_logger(__name__)
logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60.0
UNSET: object = object()  # «поле не менять» (None — осмысленное значение: вернуть заводской текст)

# Сообщения Telegram об ошибках разметки/эмодзи/длины — признак того, что виноват шаблон, а не получатель.
_TEMPLATE_ERROR_MARKERS = ('parse entities', 'entity', 'emoji', 'too long', 'text is empty')


@dataclass(frozen=True)
class Override:
    key: str
    template: str | None
    button_text: str | None
    enabled: bool
    updated_at: datetime | None
    updated_by_user_id: int | None


@dataclass(frozen=True)
class Rendered:
    text: str
    default_text: str
    button_text: str | None
    default_button_text: str | None
    enabled: bool
    is_custom: bool


class TemplateValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__('; '.join(errors))
        self.errors = errors


# --- кэш правок -------------------------------------------------------------------------------------------

_cache: dict[str, Override] | None = None
_loaded_at: float = 0.0


def invalidate_cache() -> None:
    global _cache, _loaded_at
    _cache = None
    _loaded_at = 0.0


async def load_overrides(db: AsyncSession) -> dict[str, Override]:
    """Правки из ПЕРЕДАННОЙ сессии (видит и её незакоммиченные изменения) — для экранов редактора."""
    rows = (await db.execute(select(MessageTemplate))).scalars().all()
    return {
        row.key: Override(row.key, row.template, row.button_text, row.enabled, row.updated_at, row.updated_by_user_id)
        for row in rows
    }


def _invalidate_after_commit(db: AsyncSession) -> None:
    """Кэш сбрасывается ПОСЛЕ коммита: до него запись видна только этой сессии, и читатель, перечитав БД
    раньше, закэшировал бы старое на целую минуту."""
    event.listen(db.sync_session, 'after_commit', lambda session: invalidate_cache(), once=True)


async def get_overrides(*, now: float | None = None) -> dict[str, Override]:
    """Правки владельца по ключам. Таблица маленькая (≤ 15 строк): кэш живёт CACHE_TTL_SECONDS и
    сбрасывается после коммита сохранения/сброса. Сбой БД → прошлый кэш либо пусто (заводские тексты)."""
    global _cache, _loaded_at
    current = time.monotonic() if now is None else now
    if _cache is not None and current - _loaded_at < CACHE_TTL_SECONDS:
        return _cache
    try:
        async with AsyncSessionLocal() as db:
            _cache = await load_overrides(db)
        _loaded_at = current
    except Exception:
        log.warning('templates_load_failed', exc_info=True)
    return _cache if _cache is not None else {}


# --- сохранение и сброс -----------------------------------------------------------------------------------


async def update_template(
    db: AsyncSession,
    key: str,
    *,
    admin_user_id: int | None,
    template: object = UNSET,
    button_text: object = UNSET,
    enabled: object = UNSET,
) -> MessageTemplate:
    """Частичное обновление правки. Валидирует; НЕ коммитит (коммит — на вызывающем), кэш сбрасывается после коммита."""
    event = get_event(key)  # неизвестный ключ -> UnknownEventError
    errors: list[str] = []
    if template is not UNSET and template is not None:
        errors += validate_template(event, str(template)).errors
    if button_text is not UNSET and button_text is not None:
        errors += validate_button_text(event, str(button_text))
    if errors:
        raise TemplateValidationError(errors)

    row = await db.get(MessageTemplate, key)
    if row is None:
        row = MessageTemplate(key=key, enabled=True)
        db.add(row)
    if template is not UNSET:
        row.template = template  # type: ignore[assignment]
    if button_text is not UNSET:
        row.button_text = button_text  # type: ignore[assignment]
    if enabled is not UNSET:
        row.enabled = bool(enabled)
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by_user_id = admin_user_id
    await db.flush()
    _invalidate_after_commit(db)
    log.info(
        'template_updated', key=key, admin_user_id=admin_user_id, customised=row.template is not None,
        enabled=row.enabled, length=len(row.template or ''),
    )
    return row


async def reset_template(db: AsyncSession, key: str, *, admin_user_id: int | None = None) -> bool:
    """Удаляет правку целиком (текст, кнопку, флаг). True, если она была. Коммит — на вызывающем (кэш сбросится после него)."""
    get_event(key)
    result = await db.execute(delete(MessageTemplate).where(MessageTemplate.key == key))
    _invalidate_after_commit(db)
    log.info('template_reset', key=key, admin_user_id=admin_user_id, existed=result.rowcount > 0)
    return result.rowcount > 0


# --- рендер -----------------------------------------------------------------------------------------------


def _miniapp_enabled() -> bool:
    return bool(settings.MINIAPP_URL)


def compose(event: EventDef, override: Override | None, variables: Mapping[str, object]) -> Rendered:
    default_text = render_template(event.default_template, variables)
    is_custom = bool(override and override.template is not None)
    text = render_template(override.template, variables) if is_custom else default_text  # type: ignore[union-attr,arg-type]
    default_button = event.button_label(_miniapp_enabled())
    button = None
    if event.has_button:
        button = override.button_text if override and override.button_text else default_button
    return Rendered(
        text=text,
        default_text=default_text,
        button_text=button,
        default_button_text=default_button,
        enabled=override.enabled if override else True,
        is_custom=is_custom,
    )


async def render_message(key: str, **variables: object) -> Rendered:
    event = get_event(key)
    overrides = await get_overrides()
    return compose(event, overrides.get(key), variables)


async def build_preview(key: str, *, template: str | None = None, button_text: str | None = None) -> Rendered:
    """Рендер с ПРИМЕРАМИ переменных. Переданные template/button_text заменяют текущие правки (не сохраняются)."""
    event = get_event(key)
    current = (await get_overrides()).get(key)
    override = Override(
        key=key,
        template=template if template is not None else (current.template if current else None),
        button_text=button_text if button_text is not None else (current.button_text if current else None),
        enabled=True,
        updated_at=None,
        updated_by_user_id=None,
    )
    return compose(event, override, event.samples())


# --- отправка ---------------------------------------------------------------------------------------------


def is_template_error(error: TelegramBadRequest) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _TEMPLATE_ERROR_MARKERS)


async def _deliver(bot: Bot, *, telegram_id: int, text: str, reply_markup) -> None:
    """Одна отправка. TelegramBadRequest пробрасывается (решает вызывающий); остальные ошибки
    гасятся, один повтор при flood-control — как в прежнем _safe_send."""
    try:
        await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
    except TelegramBadRequest:
        raise
    except TelegramRetryAfter as error:
        logger.warning('Flood control, жду %s сек и повторяю telegram_id=%s', error.retry_after, telegram_id)
        await asyncio.sleep(error.retry_after + 1)
        try:
            await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
        except TelegramBadRequest:
            raise
        except Exception:
            logger.warning('Не удалось отправить уведомление telegram_id=%s (после ретрая)', telegram_id, exc_info=True)
    except Exception:
        logger.warning('Не удалось отправить уведомление telegram_id=%s', telegram_id, exc_info=True)


async def send_templated(bot: Bot, *, telegram_id: int, key: str, **variables: object) -> None:
    """Отправляет автоматическое сообщение по шаблону. НИКОГДА не бросает исключение: пользователь мог
    заблокировать бота, а сбой уведомления не должен ронять платёж или фоновую задачу."""
    try:
        rendered = await render_message(key, **variables)
    except Exception:
        logger.exception('Не удалось подготовить сообщение key=%s', key)
        return
    if not rendered.enabled:
        log.info('notification_skipped', key=key, telegram_id=telegram_id, reason='disabled')
        return

    try:
        await _deliver(bot, telegram_id=telegram_id, text=rendered.text, reply_markup=build_keyboard(key, rendered.button_text))
    except TelegramBadRequest as error:
        customised = rendered.is_custom or rendered.button_text != rendered.default_button_text
        if not (customised and is_template_error(error)):
            logger.warning('Не удалось отправить уведомление telegram_id=%s', telegram_id, exc_info=True)
            return
        log.warning('template_fallback', key=key, telegram_id=telegram_id, reason=str(error)[:200])
        try:
            await _deliver(
                bot, telegram_id=telegram_id, text=rendered.default_text,
                reply_markup=build_keyboard(key, rendered.default_button_text),
            )
        except Exception:
            logger.warning('Не удалось отправить заводской текст telegram_id=%s', telegram_id, exc_info=True)


async def send_test_message(
    bot: Bot, *, telegram_id: int, key: str, template: str | None = None, button_text: str | None = None
) -> None:
    """Отправляет предпросмотр (с примерами переменных). Ошибки Telegram НЕ гасятся — админ должен
    увидеть причину (например, недопустимое кастомное эмодзи)."""
    rendered = await build_preview(key, template=template, button_text=button_text)
    await bot.send_message(
        chat_id=telegram_id, text=rendered.text, reply_markup=build_keyboard(key, rendered.button_text)
    )
