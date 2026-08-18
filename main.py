"""Точка входа. Пока без FastAPI/webserver — тот появится вместе с Mini App (этап 2)."""

from __future__ import annotations

import asyncio
import logging

from app.bot import setup_bot
from app.database.database import AsyncSessionLocal, init_sqlite_pragmas

logger = logging.getLogger(__name__)


async def _warn_if_no_active_tariff() -> None:
    """Диагностика частой ошибки на старте локальной разработки: 'Тариф временно
    недоступен' в боте почти всегда означает, что scripts/seed.py не был запущен
    ПРОТИВ ТОЙ ЖЕ БД, к которой сейчас подключается бот (например DATABASE_URL
    в .env указывает на другой файл, чем во время сидирования, либо seed.py
    просто не запускали). Явно предупреждаем в логах при старте, а не только
    молча показываем ошибку пользователю бота."""
    from sqlalchemy import select

    from app.database.models import Tariff

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Tariff.id).where(Tariff.is_active.is_(True)).limit(1))
        if result.scalar_one_or_none() is None:
            logger.warning(
                'Активных тарифов не найдено — покупка/продление/подарок будут показывать '
                '"Тариф временно недоступен". Запустите: .venv\\Scripts\\python.exe scripts\\seed.py'
            )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    await init_sqlite_pragmas()
    await _warn_if_no_active_tariff()

    bot, dp = await setup_bot()

    # === BACKGROUND TASKS (только agent:admin-support-notifications трогает этот блок) ===
    from app.services.background import expiry_checker_loop, payment_poll_loop, traffic_sync_loop

    background_tasks: list[asyncio.Task] = [
        asyncio.create_task(expiry_checker_loop(bot)),
        asyncio.create_task(traffic_sync_loop()),
        asyncio.create_task(payment_poll_loop(bot)),
    ]
    # === END BACKGROUND TASKS ===

    try:
        await dp.start_polling(bot, skip_updates=False)
    finally:
        for task in background_tasks:
            task.cancel()


if __name__ == '__main__':
    asyncio.run(main())
