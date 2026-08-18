"""Владелец: агент admin-support-notifications. Вызывается из subscription.py
(успешная оплата), referral_service.py (бонус рефереру), gift_service.py
(подарок активирован), background-задачи expiry_checker (напоминания).
См. §12а clone-architecture.md.

Сигнатуры уже используются другими модулями "на веру" — не менять без
согласования (иначе сломаются вызовы из subscription.py/referral_service.py).

Каждая функция — тонкая обёртка над bot.send_message. Пользователь мог
заблокировать бота или удалить чат — это НЕ должно ронять вызывающий код
(платёж/реферальное начисление/фоновая задача), поэтому все ошибки
перехватываются и только логируются.
"""

from __future__ import annotations

import logging

from aiogram import Bot

logger = logging.getLogger(__name__)


async def _safe_send(bot: Bot, *, telegram_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    except Exception:
        logger.warning('Не удалось отправить уведомление telegram_id=%s', telegram_id, exc_info=True)


async def notify_payment_success(bot: Bot, *, telegram_id: int, amount_kopeks: int, description: str) -> None:
    text = f'✅ Оплата на сумму {amount_kopeks / 100:.2f}₽ прошла успешно. {description}'
    await _safe_send(bot, telegram_id=telegram_id, text=text)


async def notify_referral_bonus(bot: Bot, *, telegram_id: int, amount_kopeks: int) -> None:
    text = f'🎉 Вам начислено {amount_kopeks / 100:.2f}₽ реферальных бонусов!'
    await _safe_send(bot, telegram_id=telegram_id, text=text)


async def notify_subscription_expiring(bot: Bot, *, telegram_id: int, days_left: int) -> None:
    text = f'⏳ Ваша подписка истекает через {days_left} дн.'
    await _safe_send(bot, telegram_id=telegram_id, text=text)


async def notify_subscription_expired(bot: Bot, *, telegram_id: int) -> None:
    text = '❌ Ваша подписка истекла. Продлите её в главном меню.'
    await _safe_send(bot, telegram_id=telegram_id, text=text)


async def notify_gift_redeemed_to_gifter(bot: Bot, *, gifter_telegram_id: int, recipient_username: str | None) -> None:
    who = f'@{recipient_username}' if recipient_username else 'пользователь'
    text = f'🎁 Ваш подарок активировал {who}!'
    await _safe_send(bot, telegram_id=gifter_telegram_id, text=text)


async def notify_balance_changed(bot: Bot, *, telegram_id: int, amount_kopeks: int, new_balance_kopeks: int) -> None:
    """Уведомление о ручном начислении/списании баланса администратором
    (portированное поведение из оригинального бота, см. UserService._send_balance_notification) —
    без упоминания имени админа, оно не должно попадать в текст для пользователя."""
    if amount_kopeks > 0:
        text = (
            f'💰 Баланс пополнен!\n\n'
            f'Сумма: +{amount_kopeks / 100:.2f}₽\n'
            f'Текущий баланс: {new_balance_kopeks / 100:.2f}₽'
        )
    else:
        text = (
            f'💸 Средства списаны с баланса\n\n'
            f'Сумма: -{abs(amount_kopeks) / 100:.2f}₽\n'
            f'Текущий баланс: {new_balance_kopeks / 100:.2f}₽'
        )
    await _safe_send(bot, telegram_id=telegram_id, text=text)
