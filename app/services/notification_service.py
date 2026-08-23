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

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import settings

logger = logging.getLogger(__name__)


async def _safe_send(
    bot: Bot, *, telegram_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    try:
        await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
    except TelegramRetryAfter as error:
        # Один ретрай после паузы — не бесконечный, чтобы застрявший получатель
        # не блокировал фоновую задачу навсегда. Найдено вживую (см. диалог
        # 2026-08-21): массовый прогон winback/welcome_nudge по мигрированным
        # тестовым юзерам без единой паузы упёрся в Flood control ровно так.
        logger.warning('Flood control, жду %s сек и повторяю telegram_id=%s', error.retry_after, telegram_id)
        await asyncio.sleep(error.retry_after + 1)
        try:
            await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
        except Exception:
            logger.warning('Не удалось отправить уведомление telegram_id=%s (после ретрая)', telegram_id, exc_info=True)
    except Exception:
        logger.warning('Не удалось отправить уведомление telegram_id=%s', telegram_id, exc_info=True)


async def notify_payment_success(bot: Bot, *, telegram_id: int, amount_kopeks: int, description: str) -> None:
    text = f'✅ Оплата на сумму {amount_kopeks / 100:.2f}₽ прошла успешно. {description}'
    await _safe_send(bot, telegram_id=telegram_id, text=text)


async def notify_referral_bonus(bot: Bot, *, telegram_id: int, amount_kopeks: int) -> None:
    text = f'🎉 Вам начислено {amount_kopeks / 100:.2f}₽ реферальных бонусов!'
    await _safe_send(bot, telegram_id=telegram_id, text=text)


async def notify_referral_invite_bonus(bot: Bot, *, telegram_id: int, bonus_days: int) -> None:
    text = (
        f'🚀 По вашей ссылке зарегистрировался друг — начислено +{bonus_days} дн. подписки!\n\n'
        'Приглашайте ещё — бонус начисляется за каждого нового друга.'
    )
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


async def notify_gift_code_ready(bot: Bot, *, telegram_id: int, link: str) -> None:
    """Платёж за подарок подтверждён асинхронно (payment_poll_loop) — исходное
    сообщение бота уже недоступно для редактирования, поэтому шлём новое."""
    text = (
        f'🎉 Оплата прошла успешно! Подарочный код создан.\n\n'
        f'Отправьте эту ссылку тому, кому хотите подарить подписку:\n{link}\n\n'
        f'Код действителен 30 дней.'
    )
    await _safe_send(bot, telegram_id=telegram_id, text=text)


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


async def notify_autopay_activated(bot: Bot, *, telegram_id: int) -> None:
    text = '🔄 Автоплатёж подключён — подписка будет продлеваться автоматически каждый месяц.'
    await _safe_send(bot, telegram_id=telegram_id, text=text)


async def notify_autopay_charge_failed(bot: Bot, *, telegram_id: int) -> None:
    text = (
        '⚠️ Не удалось списать автоплатёж — проверьте, что на карте/счёте достаточно средств.\n\n'
        'Подписка продолжает действовать до текущей даты окончания.'
    )
    await _safe_send(bot, telegram_id=telegram_id, text=text)


async def notify_autopay_stopped(bot: Bot, *, telegram_id: int) -> None:
    text = (
        '🔕 Автоплатёж отключён (банк отклонил привязку или списания подряд не проходят).\n\n'
        'Подписку можно продлить вручную в любой момент.'
    )
    await _safe_send(bot, telegram_id=telegram_id, text=text)


# === Автоматические триггеры рассылок (см. app/services/background.py,
# диалог 2026-08-21: "чтобы слались автоматом по событиям, напоминалки") —
# в отличие от остальных функций выше (реакция на конкретное действие юзера),
# эти три вызываются фоновыми циклами по условию времени/состояния, не по прямому
# действию. Каждая — с кнопкой в один тап, а не просто текст, потому что цель
# уведомления — вернуть юзера в конкретный экран, а не просто сообщить факт. ===


def _renew_button(text: str) -> InlineKeyboardButton:
    """Ведёт сразу на экран оплаты Mini App (сам подставляет тариф/период/способ
    по умолчанию — см. Payment.tsx), а не в чат-сценарий выбора тарифа. Пока
    MINIAPP_URL не задан (нет https-домена) — фолбэк на прежний callback_data,
    тот же паттерн, что в kb_subscription_active (handlers/subscription.py)."""
    if settings.MINIAPP_URL:
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=f'{settings.MINIAPP_URL}/payment'))
    from app.keyboards.main_menu import CB_SUBSCRIPTION_RENEW

    return InlineKeyboardButton(text=text, callback_data=CB_SUBSCRIPTION_RENEW)


async def notify_winback(bot: Bot, *, telegram_id: int) -> None:
    text = (
        '👋 Соскучились? Ваша подписка уже некоторое время неактивна — '
        'самое время вернуться, пока для вас держим ваш профиль и настройки.'
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[_renew_button('💎 Возобновить подписку')]])
    await _safe_send(bot, telegram_id=telegram_id, text=text, reply_markup=keyboard)


async def notify_abandoned_payment(bot: Bot, *, telegram_id: int) -> None:
    text = (
        '💳 Похоже, оплата не завершилась. Если передумали или что-то пошло не '
        'так — можно оформить заново, это займёт минуту.'
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[_renew_button('🔁 Попробовать снова')]])
    await _safe_send(bot, telegram_id=telegram_id, text=text, reply_markup=keyboard)


async def notify_welcome_nudge(bot: Bot, *, telegram_id: int) -> None:
    text = (
        '🔐 Не забыли про VPN? Пробный период уже начался — попробуйте подключиться '
        'сейчас, а когда пробный период закончится, сможете оформить подписку в один тап.'
    )
    # Дэшборд Mini App (не сразу /payment — юзер ещё на триале, экран сам
    # предложит подключиться/посмотреть статус, а не давит на оплату), фолбэк —
    # прежний чат-сценарий 'sub:buy'.
    if settings.MINIAPP_URL:
        button = InlineKeyboardButton(text='🚀 Открыть приложение', web_app=WebAppInfo(url=settings.MINIAPP_URL))
    else:
        button = InlineKeyboardButton(text='🚀 Открыть меню', callback_data='sub:buy')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])
    await _safe_send(bot, telegram_id=telegram_id, text=text, reply_markup=keyboard)
