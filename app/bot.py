"""Сборка Bot/Dispatcher. main.py вызывает только setup_bot()."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.handlers import register_all_handlers
from app.middlewares.auth import AuthMiddleware

logger = logging.getLogger(__name__)


async def setup_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    storage = MemoryStorage()
    if settings.REDIS_URL:
        from aiogram.fsm.storage.redis import RedisStorage

        try:
            storage = RedisStorage.from_url(settings.REDIS_URL)
            # from_url ленивый — не открывает соединение, только валидирует
            # URL, поэтому реального обрыва тут не поймать. ping() форсирует
            # первый round-trip: если Redis недоступен, лучше сразу упасть на
            # MemoryStorage с явным логом, чем молча потерять FSM-состояние
            # (шаги диалогов) на первом же апдейте в проде без Redis.
            await storage.redis.ping()
            logger.info('FSM storage: Redis (%s)', settings.REDIS_URL)
        except Exception:
            logger.exception('Redis недоступен (REDIS_URL=%s) — FSM storage: in-memory (состояние не переживёт рестарт)', settings.REDIS_URL)
            storage = MemoryStorage()
    else:
        logger.warning('REDIS_URL не задан — FSM storage: in-memory (состояние не переживёт рестарт бота)')

    dp = Dispatcher(storage=storage)

    dp.update.middleware(AuthMiddleware())

    register_all_handlers(dp)

    return bot, dp
