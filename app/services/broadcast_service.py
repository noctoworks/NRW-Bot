"""Рассылка по пользователям: аудитории и кнопки-конструктор. Общий код для бота
(app/handlers/admin.py) и веб-админки (app/cabinet/broadcast_routes.py) — единственное место,
где живут категории аудитории и набор кнопок, без дублирования."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Subscription, Tariff, User
from app.handlers.promocode import CB_PROMO_ENTER
from app.keyboards.main_menu import CB_MENU_MAIN, CB_REFERRAL_MENU, CB_SUBSCRIPTION_MY, CB_SUBSCRIPTION_RENEW, CB_SUPPORT_MENU

BROADCAST_TARGETS: dict[str, str] = {
    'all': '👥 Всем',
    'active': '📱 С подпиской',
    'no_sub': '❌ Без подписки',
    'expiring': '⏰ Истекающие',
    'expired': '🔚 Истёкшие',
}

# Кнопки-конструктор для тела рассылки — используют РЕАЛЬНЫЕ callback_data других модулей
# (main_menu.py/referral.py/promocode.py/support.py): при клике по кнопке в разосланном
# сообщении сработает штатный хендлер соответствующего модуля, это не заглушки.
BROADCAST_BUTTONS: dict[str, dict[str, str]] = {
    'subscription': {'text': '📱 Моя подписка', 'callback': CB_SUBSCRIPTION_MY},
    'renew': {'text': '💎 Продлить подписку', 'callback': CB_SUBSCRIPTION_RENEW},
    'referrals': {'text': '🤝 Партнёрка', 'callback': CB_REFERRAL_MENU},
    'promocode': {'text': '🎫 Промокод', 'callback': CB_PROMO_ENTER},
    'support': {'text': '🛠️ Техподдержка', 'callback': CB_SUPPORT_MENU},
    'home': {'text': '🏠 На главную', 'callback': CB_MENU_MAIN},
}
BROADCAST_BUTTON_ROWS: tuple[tuple[str, ...], ...] = (
    ('subscription', 'renew'),
    ('referrals', 'promocode'),
    ('support',),
    ('home',),
)
DEFAULT_BROADCAST_BUTTONS: tuple[str, ...] = ('home',)

ALLOWED_MEDIA_TYPES = frozenset({'photo', 'video', 'document'})


async def target_users(db: AsyncSession, target: str) -> list[User]:
    """Единая функция и для счётчика (len(...)), и для реальной выборки — то же решение, что
    было в handlers/admin.py, перенесено без изменения поведения (неизвестный target — []).
    now, timedelta, timezone: даты хранятся в UTC (see также app/services/time_utils.py)."""
    now = datetime.now(timezone.utc)

    if target == 'all':
        stmt = select(User)
    elif target == 'active':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(Subscription.status == 'active')
    elif target == 'no_sub':
        has_active = (
            select(Subscription.id)
            .where(Subscription.user_id == User.id, Subscription.status == 'active')
            .correlate(User)
            .exists()
        )
        stmt = select(User).where(~has_active)
    elif target == 'expiring':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(
            Subscription.status == 'active',
            Subscription.end_date <= now + timedelta(days=3),
            Subscription.end_date > now,
        )
    elif target == 'expired':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(Subscription.status == 'expired')
    elif target.startswith('tariff:'):
        tariff_id = int(target.split(':', 1)[1])
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(
            Subscription.status == 'active', Subscription.tariff_id == tariff_id
        )
    else:
        return []

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def target_display_name(db: AsyncSession, target: str) -> str:
    if target in BROADCAST_TARGETS:
        return BROADCAST_TARGETS[target]
    if target.startswith('tariff:'):
        tariff = await db.get(Tariff, int(target.split(':', 1)[1]))
        return f'Тариф «{tariff.name}»' if tariff else 'Тариф (удалён)'
    return target


def result_keyboard(selected: list[str]) -> InlineKeyboardMarkup | None:
    ordered_keys = [k for row in BROADCAST_BUTTON_ROWS for k in row if k in selected]
    if not ordered_keys:
        return None
    rows = [[InlineKeyboardButton(text=BROADCAST_BUTTONS[k]['text'], callback_data=BROADCAST_BUTTONS[k]['callback'])] for k in ordered_keys]
    return InlineKeyboardMarkup(inline_keyboard=rows)
