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

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import settings

CB_SUBSCRIPTION_MY = 'subscription:my'
CB_SUBSCRIPTION_RENEW = 'subscription:renew'
CB_GIFT_MENU = 'gift:menu'
CB_REFERRAL_MENU = 'referral:menu'
CB_SUPPORT_MENU = 'support:menu'
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
    """Пункты, у которых уже есть готовый экран в Mini App (см. диалог: "человек
    почти всегда попадал в MiniApp"), ведут туда напрямую web_app-кнопкой, а не
    в старый текстовый сценарий бота — MiniApp полнее и это единственное место,
    где реально работает TON Connect. "Подарить подписку"/"Поддержка" остаются
    в чате: у подарков пока нет экрана в Mini App, у поддержки он и не нужен —
    это переписка с человеком, а не самообслуживание. Админ-панель — отдельный
    инструмент для персонала, не трогаем (есть свой полноценный чат-сценарий).

    Пока MINIAPP_URL не задан (нет https-домена — см. тот же паттерн в
    handlers/subscription.py::kb_subscription_active) — откатываемся на старые
    callback_data-сценарии, чтобы дев-окружение без домена не осталось без меню
    вообще."""
    if settings.MINIAPP_URL:
        rows = [
            [InlineKeyboardButton(text='🌐 Моя подписка', web_app=WebAppInfo(url=settings.MINIAPP_URL))],
            [
                InlineKeyboardButton(
                    text='💎 Продлить подписку', web_app=WebAppInfo(url=f'{settings.MINIAPP_URL}/payment')
                )
            ],
            [InlineKeyboardButton(text='🎁 Подарить подписку', callback_data=CB_GIFT_MENU)],
            [
                InlineKeyboardButton(
                    text='👥 Пригласить', web_app=WebAppInfo(url=f'{settings.MINIAPP_URL}/referral')
                ),
                InlineKeyboardButton(text='❓ Поддержка', callback_data=CB_SUPPORT_MENU),
            ],
            [
                InlineKeyboardButton(text='ℹ️ О сервисе', web_app=WebAppInfo(url=f'{settings.MINIAPP_URL}/about')),
                InlineKeyboardButton(
                    text='⚙️ Настройки', web_app=WebAppInfo(url=f'{settings.MINIAPP_URL}/settings')
                ),
            ],
        ]
    else:
        rows = [
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
    if is_admin:
        rows.append([InlineKeyboardButton(text='🛠 Админ панель', callback_data=CB_ADMIN_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
