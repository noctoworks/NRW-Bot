"""Сборка Bot/Dispatcher. main.py вызывает только setup_bot()."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.handlers import register_all_handlers
from app.middlewares.auth import AuthMiddleware


async def setup_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    storage = MemoryStorage()
    if settings.REDIS_URL:
        from aiogram.fsm.storage.redis import RedisStorage

        try:
            storage = RedisStorage.from_url(settings.REDIS_URL)
        except Exception:
            storage = MemoryStorage()

    dp = Dispatcher(storage=storage)

    dp.update.middleware(AuthMiddleware())

    register_all_handlers(dp)

    return bot, dp
