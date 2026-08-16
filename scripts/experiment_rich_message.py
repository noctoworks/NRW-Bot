"""Разовый эксперимент: узнать РЕАЛЬНЫЙ HTML-синтаксис Rich Message (Bot API 10.1),
т.к. официальная страница документации слишком большая для автоматического чтения
и я не могу достоверно процитировать точный список тегов — см. диалог. Тот же
подход, что раскрыл правду про happ://: пробуем на живом боте, а не гадаем.

Отправляет админу (первый ADMIN_TELEGRAM_IDS из .env) серию ОТДЕЛЬНЫХ rich-сообщений,
каждое — с одним кандидатом-тегом, чтобы отказ на одном не блокировал проверку
остальных. Для каждой попытки печатает в консоль: успех/ошибка от Telegram.
Дальше вы смотрите вживую в Telegram, что реально отрендерилось (или не пришло),
и присылаете мне — я закодирую только то, что подтверждено.

Запуск: .venv\\Scripts\\python.exe scripts\\experiment_rich_message.py
Ничего не пишет в БД и не трогает основной код бота — можно спокойно перезапускать.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputRichMessage

from app.config import settings

CANDIDATES: list[tuple[str, str]] = [
    ('heading (h2)', '<h2>Заголовок H2</h2><p>Обычный текст после заголовка.</p>'),
    ('blockquote', '<blockquote>Это blockquote внутри rich-сообщения.</blockquote>'),
    ('divider (hr)', '<p>Текст до разделителя</p><hr><p>Текст после разделителя</p>'),
    ('table', '<table><tr><th>Период</th><th>Цена</th></tr><tr><td>30 дн.</td><td>99₽</td></tr></table>'),
    ('details/summary', '<details><summary>Показать детали</summary><p>Скрытый текст внутри деталей.</p></details>'),
    ('sup/sub', '<p>Текст со степенью x<sup>2</sup> и индексом H<sub>2</sub>O.</p>'),
    ('list (ul/li)', '<ul><li>Пункт один</li><li>Пункт два</li></ul>'),
    ('footer', '<p>Основной текст</p><footer>Сноска снизу</footer>'),
]


async def main() -> None:
    admin_ids = sorted(settings.admin_ids())
    if not admin_ids:
        print('ADMIN_TELEGRAM_IDS пуст в .env — некому отправлять эксперимент.')
        return

    chat_id = admin_ids[0]
    bot = Bot(token=settings.BOT_TOKEN)

    print(f'Отправляю {len(CANDIDATES)} тестовых rich-сообщений в чат {chat_id}...\n')

    for label, html in CANDIDATES:
        try:
            await bot.send_rich_message(chat_id=chat_id, rich_message=InputRichMessage(html=html))
            print(f'[OK]    {label} — Telegram принял, смотрите в чате как отрендерилось')
        except TelegramBadRequest as exc:
            print(f'[FAIL]  {label} — Telegram отклонил: {exc}')
        except Exception as exc:
            print(f'[ERROR] {label} — неожиданная ошибка: {exc}')
        await asyncio.sleep(0.5)  # чтобы не словить flood-limit между сообщениями

    await bot.session.close()
    print('\nГотово. Проверьте чат с ботом и пришлите скриншот/список того, что реально отрендерилось.')


if __name__ == '__main__':
    asyncio.run(main())
