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

    # === BACKGROUND TASKS (только agent:admin-support-notifications трогает этот блок) ===
    from app.services.background import expiry_checker_loop, payment_poll_loop, traffic_sync_loop

    background_tasks: list[asyncio.Task] = [
        asyncio.create_task(expiry_checker_loop(bot)),
        asyncio.create_task(traffic_sync_loop()),
        asyncio.create_task(payment_poll_loop()),
    ]
    # === END BACKGROUND TASKS ===

    try:
        await dp.start_polling(bot, skip_updates=False)
    finally:
        for task in background_tasks:
            task.cancel()


if __name__ == '__main__':
    asyncio.run(main())
