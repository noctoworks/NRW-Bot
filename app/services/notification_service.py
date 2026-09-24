"""Автоматические сообщения бота пользователям. Вызывается из subscription.py (успешная оплата),
referral_service.py (бонус рефереру), gift_service.py (подарок активирован), background-задач
(напоминания), webhooks.py (автоплатёж).

Тексты живут в реестре шаблонов (app/services/message_templates/registry.py) и могут быть изменены
владельцем в админке (таблица message_templates); здесь — тонкие обёртки с ПРЕЖНИМИ сигнатурами
(другие модули вызывают их «на веру» — не менять). Пользователь мог заблокировать бота или удалить чат —
это НЕ должно ронять вызывающий код (платёж, начисление, фоновая задача), поэтому send_templated
никогда не бросает исключение и при сбое шаблона шлёт заводской текст."""

from __future__ import annotations

from datetime import datetime

from aiogram import Bot

from app.services.message_templates.service import send_templated
from app.services.time_utils import MOSCOW_OFFSET


def _rub(kopeks: int) -> str:
    """Сумма в рублях числом без знака ₽ (знак остаётся в тексте шаблона): 24900 -> '249.00'."""
    return f'{kopeks / 100:.2f}'


async def notify_payment_success(bot: Bot, *, telegram_id: int, amount_kopeks: int, description: str) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='payment_success', amount=_rub(amount_kopeks), description=description)


async def notify_referral_bonus(bot: Bot, *, telegram_id: int, amount_kopeks: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='referral_bonus', amount=_rub(amount_kopeks))


async def notify_referral_invite_bonus(bot: Bot, *, telegram_id: int, bonus_days: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='referral_invite_bonus', bonus_days=bonus_days)


async def notify_subscription_expiring(bot: Bot, *, telegram_id: int, days_left: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='subscription_expiring', days_left=days_left)


async def notify_subscription_expired(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='subscription_expired')


def _until_moscow(deadline: datetime) -> str:
    """Дедлайн скидки для текста: aware UTC -> «27.09 в 15:00 МСК» (Москва — UTC+3 круглый год)."""
    moscow = deadline + MOSCOW_OFFSET
    return f'{moscow:%d.%m} в {moscow:%H:%M} МСК'


async def notify_trial_ending(bot: Bot, *, telegram_id: int, discount_percent: int, deadline: datetime) -> None:
    """За день до конца триала, пока действует скидка (вместо notify_subscription_expiring для триальных)."""
    await send_templated(
        bot, telegram_id=telegram_id, key='trial_ending', discount_percent=discount_percent, until=_until_moscow(deadline)
    )


async def notify_trial_expired(bot: Bot, *, telegram_id: int, discount_percent: int, deadline: datetime) -> None:
    """Триал закончился, скидка ещё действует (вместо notify_subscription_expired для триальных)."""
    await send_templated(
        bot, telegram_id=telegram_id, key='trial_expired', discount_percent=discount_percent, until=_until_moscow(deadline)
    )


async def notify_gift_redeemed_to_gifter(bot: Bot, *, gifter_telegram_id: int, recipient_username: str | None) -> None:
    who = f'@{recipient_username}' if recipient_username else 'пользователь'
    await send_templated(bot, telegram_id=gifter_telegram_id, key='gift_redeemed', who=who)


async def notify_gift_code_ready(bot: Bot, *, telegram_id: int, link: str) -> None:
    """Платёж за подарок подтверждён асинхронно (payment_poll_loop) — исходное сообщение бота уже
    недоступно для редактирования, поэтому шлём новое."""
    await send_templated(bot, telegram_id=telegram_id, key='gift_code_ready', link=link)


async def notify_balance_changed(bot: Bot, *, telegram_id: int, amount_kopeks: int, new_balance_kopeks: int) -> None:
    """Ручное начисление/списание баланса администратором — без имени админа в тексте для пользователя."""
    key = 'balance_credited' if amount_kopeks > 0 else 'balance_debited'
    await send_templated(bot, telegram_id=telegram_id, key=key, amount=_rub(abs(amount_kopeks)), balance=_rub(new_balance_kopeks))


async def notify_autopay_activated(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='autopay_activated')


async def notify_autopay_charge_failed(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='autopay_charge_failed')


async def notify_autopay_stopped(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='autopay_stopped')


# === Автоматические триггеры рассылок (app/services/background.py): вызываются фоновыми циклами по
# условию времени/состояния. Кнопка ведёт в конкретный экран Mini App — её подпись (заводская или
# правка владельца) и действие собирает app/services/message_templates/keyboards.py. ===


async def notify_winback(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='winback')


async def notify_abandoned_payment(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='abandoned_payment')


async def notify_welcome_nudge(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='welcome_nudge')
