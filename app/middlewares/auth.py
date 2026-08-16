"""Загружает/создаёт User по telegram_id, кладёт db-сессию и db_user в контекст хендлера.

Регистрация нового пользователя (INSERT User) сюда НЕ входит — это ответственность
handlers/start.py (см. §9.1 clone-architecture.md): middleware только читает,
handler решает, что делать с отсутствующим пользователем (запустить FSM регистрации).

Единственный источник истины для User.is_admin — settings.ADMIN_TELEGRAM_IDS (.env).
Никакой другой способ стать админом в системе сейчас не предусмотрен (admin.py умеет
только блокировать/разблокировать пользователей, не назначать is_admin), поэтому
синхронизируем это поле на каждый апдейт — правка ADMIN_TELEGRAM_IDS подхватывается
без пересоздания БД. Найдено вживую: ни один из четырёх параллельных модулей не
выставлял is_admin вообще — /admin не работал бы ни для кого."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.config import settings
from app.database.database import AsyncSessionLocal
from app.database.models import User
from sqlalchemy import select


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user = data.get('event_from_user')
        if telegram_user is None:
            return await handler(event, data)

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_user.id))
            db_user = result.scalar_one_or_none()

            if db_user is not None:
                should_be_admin = telegram_user.id in settings.admin_ids()
                if db_user.is_admin != should_be_admin:
                    db_user.is_admin = should_be_admin
                # "Онлайн сейчас/сегодня/за неделю" и "Последняя активность" в
                # админке (см. диалог, Фаза 2) считаются от этого поля.
                db_user.last_activity_at = datetime.now(timezone.utc)
                # Раз дошли до хендлера — бот у пользователя точно не заблокирован
                # (иначе Telegram не доставил бы апдейт нам).
                if db_user.blocked_bot:
                    db_user.blocked_bot = False

            data['db'] = session
            data['db_user'] = db_user

            response = await handler(event, data)
            await session.commit()
            return response
