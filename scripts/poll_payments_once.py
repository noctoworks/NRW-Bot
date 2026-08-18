"""Ручной разовый опрос pending-платежей (PAYMENTS_MODE=real) — для живого теста
Platega без ожидания интервала payment_poll_loop (по умолчанию 600с). После оплаты
на странице Platega запустите этот скрипт, чтобы сразу проверить выдачу
подписки/подарочного кода.

Запуск: .venv\\Scripts\\python.exe scripts\\poll_payments_once.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from app.services.background import run_payment_poll_once


async def main() -> None:
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await run_payment_poll_once(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
