"""Точка входа. FastAPI (Mini App API, /cabinet/*) поднимается опционально —
только когда CABINET_ENABLED=true, см. app/cabinet/app.py."""

from __future__ import annotations

import asyncio
import logging

from app.bot import setup_bot
from app.config import settings
from app.database.database import AsyncSessionLocal, engine, init_sqlite_pragmas
from app.external.http import close_http_client
from app.logging_setup import get_logger, setup_logging
from app.runtime import cancel_and_wait, supervise

logger = logging.getLogger(__name__)
log = get_logger(__name__)


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
    setup_logging(level=settings.LOG_LEVEL, fmt=settings.LOG_FORMAT)
    log.info(
        'startup',
        payments_mode=settings.PAYMENTS_MODE,
        remnawave_mode=settings.REMNAWAVE_MODE,
        cabinet_enabled=settings.CABINET_ENABLED,
        database='sqlite' if settings.is_sqlite() else 'postgres',
        redis=bool(settings.REDIS_URL),
        bulk_notifications=settings.BULK_NOTIFICATIONS_ENABLED,
        log_format=settings.LOG_FORMAT,
    )

    await init_sqlite_pragmas()
    await _warn_if_no_active_tariff()

    from app.services.broadcast_service import mark_interrupted_broadcasts

    await mark_interrupted_broadcasts()

    bot, dp = await setup_bot()

    # === BACKGROUND TASKS (только agent:admin-support-notifications трогает этот блок) ===
    from app.services.background import (
        expiry_checker_loop,
        payment_poll_loop,
        traffic_sync_loop,
        welcome_nudge_loop,
        winback_loop,
    )

    background_tasks: dict[str, asyncio.Task] = {
        'expiry_checker': asyncio.create_task(expiry_checker_loop(bot), name='expiry_checker'),
        'traffic_sync': asyncio.create_task(traffic_sync_loop(), name='traffic_sync'),
        'payment_poll': asyncio.create_task(payment_poll_loop(bot), name='payment_poll'),
    }
    if settings.BULK_NOTIFICATIONS_ENABLED:
        background_tasks['winback'] = asyncio.create_task(winback_loop(bot), name='winback')
        background_tasks['welcome_nudge'] = asyncio.create_task(welcome_nudge_loop(bot), name='welcome_nudge')
    else:
        logger.warning('BULK_NOTIFICATIONS_ENABLED=false — winback_loop/welcome_nudge_loop не запущены')
    # === END BACKGROUND TASKS ===

    cabinet_server = None
    if settings.CABINET_ENABLED:
        import uvicorn

        from app.cabinet.app import create_app

        cabinet_server = uvicorn.Server(
            uvicorn.Config(
                create_app(bot),
                host='0.0.0.0',
                port=settings.CABINET_PORT,
                log_config=None,  # логи uvicorn идут через наш structlog-конвейер
                access_log=False,  # запросы логирует HTTP-middleware кабинета
                log_level='warning',
            )
        )
        background_tasks['cabinet'] = asyncio.create_task(cabinet_server.serve(), name='cabinet')
        logger.info('Cabinet API запущен на порту %s', settings.CABINET_PORT)

    polling: asyncio.Task | None = None
    try:
        # Обязательно перед polling: если на этом BOT_TOKEN ранее был выставлен
        # Telegram-вебхук (см. переезд со старого бота, admin.nocto.online/webhook*
        # в его Caddy-конфиге), getUpdates будет молча возвращать пусто, пока
        # вебхук не снят явно — Telegram не отдаёт апдейты через оба канала сразу.
        await bot.delete_webhook(drop_pending_updates=False)
        # polling — тоже под надзором: падение uvicorn/фонового цикла роняет
        # процесс (контейнер перезапустится), а не оставляет бота "наполовину живым".
        polling = asyncio.create_task(dp.start_polling(bot, skip_updates=False), name='polling')
        await supervise({'polling': polling, **background_tasks})
    finally:
        if cabinet_server is not None:
            cabinet_server.should_exit = True
        tasks = [*background_tasks.values()]
        if polling is not None:
            tasks.append(polling)
        log.info('shutdown')
        await cancel_and_wait(tasks)
        await close_http_client()
        await bot.session.close()
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
