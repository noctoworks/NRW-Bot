"""Главное меню — единый источник callback_data для всех модулей. Не дублировать
эти строки хардкодом в других файлах, импортировать константы отсюда.

Соответствие кнопка -> владелец-модуль (см. README агентов в PROGRESS.md):
    subscription:my     -> handlers/subscription.py  ("Моя подписка")
    subscription:renew  -> handlers/subscription.py  ("Продлить подписку")
    gift:menu            -> handlers/gift.py           ("Подарить подписку")
    referral:menu         -> handlers/referral.py        ("Пригласить")
    support:menu           -> handlers/support.py          ("Поддержка")
    info:about               -> handlers/start.py             ("О сервисе", статика)
    settings:menu              -> handlers/start.py             ("Настройки", язык)
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CB_SUBSCRIPTION_MY = 'subscription:my'
CB_SUBSCRIPTION_RENEW = 'subscription:renew'
CB_GIFT_MENU = 'gift:menu'
CB_REFERRAL_MENU = 'referral:menu'
CB_SUPPORT_MENU = 'support:menu'
CB_INFO_ABOUT = 'info:about'
CB_SETTINGS_MENU = 'settings:menu'


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🌐 Моя подписка', callback_data=CB_SUBSCRIPTION_MY)],
            [InlineKeyboardButton(text='💎 Продлить подписку', callback_data=CB_SUBSCRIPTION_RENEW)],
            [InlineKeyboardButton(text='🎁 Подарить подписку', callback_data=CB_GIFT_MENU)],
            [
                InlineKeyboardButton(text='👥 Пригласить', callback_data=CB_REFERRAL_MENU),
                InlineKeyboardButton(text='❓ Поддержка', callback_data=CB_SUPPORT_MENU),
            ],
            [
                InlineKeyboardButton(text='ℹ️ О сервисе', callback_data=CB_INFO_ABOUT),
                InlineKeyboardButton(text='⚙️ Настройки', callback_data=CB_SETTINGS_MENU),
            ],
        ]
    )
