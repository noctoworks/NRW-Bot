"""Главное меню — единый источник callback_data для всех модулей. Не дублировать
эти строки хардкодом в других файлах, импортировать константы отсюда.

Соответствие кнопка -> владелец-модуль (см. README агентов в PROGRESS.md):
    subscription:my     -> handlers/subscription.py  ("Моя подписка")
    subscription:renew  -> handlers/subscription.py  ("Продлить подписку")
    gift:menu            -> handlers/gift.py           ("Подарить подписку")
    referral:menu         -> handlers/referral.py        ("Пригласить")
    support:menu           -> handlers/support.py          ("Поддержка")
    proxy:menu               -> handlers/proxy.py             ("Прокси", см. диалог 2026-08-22)
    info:about               -> handlers/start.py             ("О сервисе", статика)
    settings:menu              -> handlers/start.py             ("Настройки", язык)
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import miniapp_url, settings
from app.emoji import MENU_GIFT, MENU_PROXY, MENU_REFERRAL, MENU_RENEW, MENU_SUBSCRIPTION, MENU_SUPPORT, icon_button

CB_SUBSCRIPTION_MY = 'subscription:my'
CB_SUBSCRIPTION_RENEW = 'subscription:renew'
CB_GIFT_MENU = 'gift:menu'
CB_REFERRAL_MENU = 'referral:menu'
CB_SUPPORT_MENU = 'support:menu'
CB_PROXY_MENU = 'proxy:menu'
CB_INFO_ABOUT = 'info:about'
CB_SETTINGS_MENU = 'settings:menu'

# Владелец экрана — handlers/admin.py, но константа живёт здесь (как и остальные
# callback_data главного меню), чтобы get_main_menu_keyboard() не импортировал
# admin.py (там уже импортируется main_menu.py — цикл).
CB_ADMIN_ROOT = 'admin:root'

# Возврат в главное меню — реализован в handlers/start.py (единственный владелец
# показа главного меню). Все остальные модули ссылаются на эту константу вместо
# того чтобы хардкодить строку 'menu:main' — так исключается риск рассинхрона
# (найденный баг: subscription.py использовал 'menu:main', но хендлера не было
# ни в одном модуле).
CB_MENU_MAIN = 'menu:main'


def back_to_menu_button() -> InlineKeyboardButton:
    """Единая кнопка «В меню» — используйте её вместо InlineKeyboardButton(..., callback_data='menu:main')
    напрямую, чтобы при изменении текста/эмодзи не редактировать N файлов."""
    return InlineKeyboardButton(text='⬅️ В меню', callback_data=CB_MENU_MAIN)


def get_main_menu_keyboard(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Базовый сценарий — всегда в чате бота (см. диалог: "нужно оставить также
    базовый функционал в боте", человек должен мочь оплатить и через бота, и
    через Mini App, а не только через одно из двух). Отдельной кнопки-шортката
    в Mini App здесь больше нет (см. диалог "убери кнопку Открыть приложение"),
    кроме "Моя подписка" — та теперь сама ведёт в Mini App (см. диалог), а не в
    чат-сценарий; остальной вход в Mini App остаётся точечным, только там, где
    у него есть явное преимущество (см. handlers/subscription.py, кнопки
    покупки/продления)."""
    my_subscription_button = (
        icon_button('Моя подписка', MENU_SUBSCRIPTION, web_app=WebAppInfo(url=miniapp_url()))
        if settings.MINIAPP_URL
        else icon_button('Моя подписка', MENU_SUBSCRIPTION, callback_data=CB_SUBSCRIPTION_MY)
    )
    rows: list[list[InlineKeyboardButton]] = [
        [my_subscription_button],
        [icon_button('Продлить подписку', MENU_RENEW, callback_data=CB_SUBSCRIPTION_RENEW)],
        [icon_button('Подарить подписку', MENU_GIFT, callback_data=CB_GIFT_MENU)],
    ]
    if settings.PROXY_ENABLED:
        # Сразу под "Подарить подписку" (см. диалог 2026-08-27) — отдельной
        # строкой, а не в паре с "Пригласить"/"Поддержка", фича не связана с
        # ними по смыслу.
        rows.append([icon_button('Прокси для Telegram', MENU_PROXY, callback_data=CB_PROXY_MENU)])
    rows.append(
        [
            icon_button('Пригласить', MENU_REFERRAL, callback_data=CB_REFERRAL_MENU),
            icon_button('Поддержка', MENU_SUPPORT, callback_data=CB_SUPPORT_MENU),
        ]
    )
    # Без эмодзи вообще (см. диалог) — ни fallback-символа в тексте, ни иконки.
    rows.append([InlineKeyboardButton(text='О сервисе', callback_data=CB_INFO_ABOUT)])
    if is_admin:
        rows.append([InlineKeyboardButton(text='🛠 Админ панель', callback_data=CB_ADMIN_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
