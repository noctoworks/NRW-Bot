"""Надзор за долгоживущими задачами процесса (polling, Cabinet API, фоновые циклы).

Раньше main.py создавал задачи через asyncio.create_task и не смотрел на них:
если падал uvicorn (порт занят, ошибка при старте) или умирал фоновый цикл,
бот продолжал работать без API/вебхуков, а исключение терялось. Теперь падение
любой задачи роняет процесс с понятной причиной — контейнер перезапустится
(restart: unless-stopped) вместо тихой деградации.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

logger = logging.getLogger(__name__)


class TaskStoppedError(RuntimeError):
    """Задача, которая должна жить весь срок процесса, завершилась."""


async def supervise(tasks: dict[str, asyncio.Task], *, graceful: Iterable[str] = ('polling',)) -> None:
    """Ждёт завершения ЛЮБОЙ задачи. Штатное завершение задачи из `graceful`
    (polling по SIGINT/SIGTERM) — обычный выход, возвращаемся. Любая другая
    остановка — падение или неожиданное завершение: бросаем TaskStoppedError."""
    graceful = set(graceful)
    done, _ = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_COMPLETED)
    for name, task in tasks.items():
        if task not in done:
            continue
        if task.cancelled():
            raise TaskStoppedError(f'задача {name!r} была отменена')
        error = task.exception()
        if error is not None:
            raise TaskStoppedError(f'задача {name!r} упала: {error!r}') from error
        if name in graceful:
            logger.info('Задача %r завершилась штатно — останавливаем процесс', name)
            return
        raise TaskStoppedError(f'задача {name!r} неожиданно завершилась')


async def cancel_and_wait(tasks: Iterable[asyncio.Task], *, timeout: float = 10.0) -> None:
    """Отменяет задачи и ДОЖИДАЕТСЯ их завершения (не дольше timeout), чтобы
    закрытие БД/HTTP-клиентов не гонялось с ещё работающими циклами."""
    pending = [task for task in tasks if not task.done()]
    for task in pending:
        task.cancel()
    if not pending:
        return
    _, still_running = await asyncio.wait(pending, timeout=timeout)
    if still_running:
        logger.warning('%s задач не завершились за %ss после отмены', len(still_running), timeout)
