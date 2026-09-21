"""app/runtime.py — надзор за долгоживущими задачами."""

from __future__ import annotations

import asyncio

import pytest

from app.runtime import TaskStoppedError, cancel_and_wait, supervise


async def _forever() -> None:
    await asyncio.Event().wait()


async def _boom() -> None:
    await asyncio.sleep(0)
    raise ValueError('bind failed')


async def _returns() -> None:
    await asyncio.sleep(0)


def test_crashed_task_stops_the_process_with_its_name():
    async def scenario():
        tasks = {'polling': asyncio.create_task(_forever()), 'cabinet': asyncio.create_task(_boom())}
        try:
            with pytest.raises(TaskStoppedError, match="cabinet.*bind failed"):
                await supervise(tasks)
        finally:
            await cancel_and_wait(tasks.values())

    asyncio.run(scenario())


def test_graceful_polling_exit_is_not_an_error():
    async def scenario():
        tasks = {'polling': asyncio.create_task(_returns()), 'loop': asyncio.create_task(_forever())}
        try:
            await supervise(tasks)  # не бросает
        finally:
            await cancel_and_wait(tasks.values())

    asyncio.run(scenario())


def test_unexpected_normal_exit_of_background_task_is_an_error():
    async def scenario():
        tasks = {'polling': asyncio.create_task(_forever()), 'payment_poll': asyncio.create_task(_returns())}
        try:
            with pytest.raises(TaskStoppedError, match='payment_poll'):
                await supervise(tasks)
        finally:
            await cancel_and_wait(tasks.values())

    asyncio.run(scenario())


def test_cancel_and_wait_actually_waits():
    async def scenario():
        finished = []

        async def worker():
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.05)  # "закрытие ресурсов"
                finished.append(True)

        task = asyncio.create_task(worker())
        await asyncio.sleep(0)
        await cancel_and_wait([task])
        assert finished == [True] and task.done()

    asyncio.run(scenario())
