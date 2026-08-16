"""Точка входа. Пока без FastAPI/webserver — тот появится вместе с Mini App (этап 2)."""

from __future__ import annotations

import asyncio
import logging

from app.bot import setup_bot
from app.database.database import init_sqlite_pragmas


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    await init_sqlite_pragmas()

    bot, dp = await setup_bot()
    await dp.start_polling(bot, skip_updates=False)


if __name__ == '__main__':
    asyncio.run(main())
