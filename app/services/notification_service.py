"""Владелец: агент admin-support-notifications. Вызывается из subscription.py
(успешная оплата), referral_service.py (бонус рефереру), gift_service.py
(подарок активирован), background-задачи expiry_checker (напоминания).
См. §12а clone-architecture.md.

Сигнатуры уже используются другими модулями "на веру" — не менять без
согласования (иначе сломаются вызовы из subscription.py/referral_service.py).

TODO(agent:admin-support-notifications): реализовать тело функций (просто
bot.send_message с человекочитаемым текстом; HTML parse_mode уже дефолтный
в Bot, см. app/bot.py).
"""

from __future__ import annotations

from aiogram import Bot


async def notify_payment_success(bot: Bot, *, telegram_id: int, amount_kopeks: int, description: str) -> None:
    raise NotImplementedError


async def notify_referral_bonus(bot: Bot, *, telegram_id: int, amount_kopeks: int) -> None:
    raise NotImplementedError


async def notify_subscription_expiring(bot: Bot, *, telegram_id: int, days_left: int) -> None:
    raise NotImplementedError


async def notify_subscription_expired(bot: Bot, *, telegram_id: int) -> None:
    raise NotImplementedError


async def notify_gift_redeemed_to_gifter(bot: Bot, *, gifter_telegram_id: int, recipient_username: str | None) -> None:
    raise NotImplementedError
