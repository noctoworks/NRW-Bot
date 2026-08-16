"""Загружает/создаёт User по telegram_id, кладёт db-сессию и db_user в контекст хендлера.

Регистрация нового пользователя (INSERT User) сюда НЕ входит — это ответственность
handlers/start.py (см. §9.1 clone-architecture.md): middleware только читает,
handler решает, что делать с отсутствующим пользователем (запустить FSM регистрации).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

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

            data['db'] = session
            data['db_user'] = db_user

            response = await handler(event, data)
            await session.commit()
            return response
