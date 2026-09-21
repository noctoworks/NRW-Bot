"""Логирование апдейтов Telegram: одна строка на апдейт (что пришло, от кого, за
сколько обработано) и контекст (update_id, telegram_id, ...) для всех логов внутри
обработки. Текст обычных сообщений НЕ логируется (персональные данные) — только
команда (первое слово `/...`), тип контента или callback_data.

Регистрируется как outer-middleware ПЕРВЫМ — до AuthMiddleware, чтобы поймать и
ошибки самой авторизации/БД."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.logging_setup import bind_context, clear_context, get_logger

log = get_logger(__name__)

SLOW_UPDATE_SECONDS = 3.0


def describe_update(update: Update) -> dict[str, Any]:
    """Краткое безопасное описание апдейта для лога."""
    if update.message is not None:
        text = update.message.text or ''
        if text.startswith('/'):
            return {'kind': 'command', 'action': text.split()[0][:64]}
        content_type = update.message.content_type
        return {'kind': 'message', 'action': f'<{getattr(content_type, "value", content_type)}>'}
    if update.callback_query is not None:
        return {'kind': 'callback', 'action': (update.callback_query.data or '')[:64]}
    return {'kind': str(update.event_type), 'action': ''}


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        clear_context()  # контекст предыдущего апдейта не должен протекать в этот
        info = describe_update(event) if isinstance(event, Update) else {'kind': type(event).__name__, 'action': ''}
        telegram_user = data.get('event_from_user')
        bind_context(
            update_id=getattr(event, 'update_id', None),
            telegram_id=telegram_user.id if telegram_user else None,
            username=telegram_user.username if telegram_user else None,
        )

        started = time.perf_counter()
        try:
            result = await handler(event, data)
        except Exception:
            log.exception('update_failed', duration_ms=_ms(started), **info)
            raise

        duration = time.perf_counter() - started
        level = log.warning if duration >= SLOW_UPDATE_SECONDS else log.info
        level('update_handled', duration_ms=round(duration * 1000), **info)
        return result


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
