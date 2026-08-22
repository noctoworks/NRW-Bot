"""Telegram-прокси (MTProto/FakeTLS через mtg) — см. диалог 2026-08-22.

Разгоняет/разблокирует сам Telegram (чаты, звонки), НЕ весь трафик пользователя —
для этого у бота уже есть VPN-подписка (см. handlers/subscription.py). Секрет
общий на всех пользователей, как в любом публичном MTProxy-боте — персональные
секреты не нужны для этого MVP (единственный secret на инстанс mtg, см.
docker-compose.yml, профиль 'proxy').
"""

from __future__ import annotations

from urllib.parse import urlencode

from aiogram import Dispatcher, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.database.models import User
from app.keyboards.main_menu import CB_PROXY_MENU, back_to_menu_button

router = Router(name='proxy')


TEXTS = {
    'ru': (
        '🔌 <b>Прокси для Telegram</b>\n\n'
        'Если сам Telegram у вас тормозит или недоступен — подключите прокси '
        'одной кнопкой ниже.\n\n'
        'Разгоняет только сам Telegram (чаты, звонки, стикеры), не весь '
        'интернет — для остального трафика используйте вашу VPN-подписку.'
    ),
    'en': (
        '🔌 <b>Proxy for Telegram</b>\n\n'
        'If Telegram itself is slow or blocked for you — connect a proxy with '
        'one tap below.\n\n'
        "It only speeds up Telegram (chats, calls, stickers), not your whole "
        'internet — for that, use your VPN subscription.'
    ),
}
BUTTON_TEXT = {'ru': '🔌 Подключить прокси', 'en': '🔌 Connect proxy'}


def _proxy_link() -> str:
    params = {'server': settings.PROXY_SERVER, 'port': str(settings.PROXY_PORT), 'secret': settings.PROXY_SECRET}
    return f'https://t.me/proxy?{urlencode(params)}'


@router.callback_query(F.data == CB_PROXY_MENU)
async def cb_proxy_menu(callback: CallbackQuery, db_user: User | None) -> None:
    if not settings.PROXY_ENABLED:
        # Кнопки в меню не должно быть вообще (get_main_menu_keyboard), но
        # старое сообщение с клавиатурой могло остаться у юзера, если фичу
        # выключили уже после того, как он открыл меню — не падаем молча.
        await callback.answer()
        return

    lang = (db_user.language if db_user else None) or 'ru'
    text = TEXTS.get(lang, TEXTS['ru'])
    button_text = BUTTON_TEXT.get(lang, BUTTON_TEXT['ru'])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button_text, url=_proxy_link())],
            [back_to_menu_button()],
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
