"""Клавиатуры автоматических сообщений с кнопкой (winback, abandoned_payment, welcome_nudge).

Раньше жили в notification_service.py. Подпись кнопки приходит снаружи (заводская или правка владельца);
кнопка ведёт в Mini App, а без MINIAPP_URL — на прежний callback чат-сценария."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import miniapp_url, settings


def _renew_button(text: str) -> InlineKeyboardButton:
    """Ведёт сразу на экран оплаты Mini App, а не в чат-сценарий выбора тарифа. Пока MINIAPP_URL
    не задан — фолбэк на callback_data, тот же паттерн, что в kb_subscription_active."""
    if settings.MINIAPP_URL:
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=miniapp_url('/payment')))
    from app.keyboards.main_menu import CB_SUBSCRIPTION_RENEW

    return InlineKeyboardButton(text=text, callback_data=CB_SUBSCRIPTION_RENEW)


def _open_app_button(text: str) -> InlineKeyboardButton:
    """Дэшборд Mini App (не сразу /payment — пользователь ещё на триале); фолбэк — чат-сценарий 'sub:buy'."""
    if settings.MINIAPP_URL:
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=miniapp_url()))
    return InlineKeyboardButton(text=text, callback_data='sub:buy')


def build_keyboard(key: str, label: str | None) -> InlineKeyboardMarkup | None:
    if label is None:
        return None
    if key in ('winback', 'abandoned_payment'):
        return InlineKeyboardMarkup(inline_keyboard=[[_renew_button(label)]])
    if key == 'welcome_nudge':
        return InlineKeyboardMarkup(inline_keyboard=[[_open_app_button(label)]])
    return None
