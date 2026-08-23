"""Реф-ссылка + статистика — см. §9.6 clone-architecture.md.

Начисление (credit_referral_earning) владеет services/referral_service.py и
вызывается из handlers/subscription.py после каждой успешной оплаты — здесь
только отображение: ссылка, кол-во приглашённых, сумма заработанного.
"""

from __future__ import annotations

from aiogram import Dispatcher, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import ReferralEarning, User
from app.keyboards.main_menu import CB_REFERRAL_MENU, back_to_menu_button
from app.services.referral_service import REFERRAL_INVITE_BONUS_DAYS

router = Router(name='referral')


TEXTS = {
    'ru': {
        'info': (
            '👥 <b>Реферальная программа</b>\n\n'
            'Приглашайте друзей и получайте {percent}% от каждой их оплаты '
            '(покупка/продление подписки, пополнение баланса) на свой баланс — '
            'плюс +{bonus_days} дн. подписки сразу, как только друг зарегистрируется '
            'по вашей ссылке.\n\n'
            'Ваша ссылка:\n<code>{link}</code>\n\n'
            'Приглашено: <b>{count}</b>\n'
            'Заработано: <b>{earned:.2f} ₽</b>'
        ),
        'no_username': (
            '\n\n⚠️ У бота не задан BOT_USERNAME в .env — замените плейсхолдер '
            'в ссылке на реальный username бота.'
        ),
    },
    'en': {
        'info': (
            '👥 <b>Referral program</b>\n\n'
            'Invite friends and get {percent}% of every payment they make '
            '(subscription purchase/renewal, balance top-up) credited to your balance — '
            'plus +{bonus_days}d of subscription instantly once a friend registers via '
            'your link.\n\n'
            'Your link:\n<code>{link}</code>\n\n'
            'Invited: <b>{count}</b>\n'
            'Earned: <b>{earned:.2f}</b>'
        ),
        'no_username': (
            '\n\n⚠️ BOT_USERNAME is not set in .env — replace the placeholder '
            'in the link with the actual bot username.'
        ),
    },
}


def _t(lang: str | None, key: str) -> str:
    return TEXTS.get(lang or 'ru', TEXTS['ru'])[key]


@router.callback_query(F.data == CB_REFERRAL_MENU)
async def cb_referral_menu(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if db_user is None:
        await callback.answer()
        return
    if db_user.is_blocked:
        await callback.answer('Ваш аккаунт заблокирован.', show_alert=True)
        return

    lang = db_user.language

    count_result = await db.execute(select(func.count(User.id)).where(User.referred_by_id == db_user.id))
    invited_count = count_result.scalar_one() or 0

    sum_result = await db.execute(
        select(func.coalesce(func.sum(ReferralEarning.amount_kopeks), 0)).where(
            ReferralEarning.user_id == db_user.id
        )
    )
    earned_kopeks = sum_result.scalar_one() or 0

    bot_username = settings.BOT_USERNAME
    if bot_username:
        link = f'https://t.me/{bot_username}?start=ref_{db_user.referral_code}'
        suffix = ''
    else:
        link = f't.me/<укажите_BOT_USERNAME>?start=ref_{db_user.referral_code}'
        suffix = _t(lang, 'no_username')

    text = _t(lang, 'info').format(
        percent=settings.REFERRAL_PERCENT,
        bonus_days=REFERRAL_INVITE_BONUS_DAYS,
        link=link,
        count=invited_count,
        earned=earned_kopeks / 100,
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    try:
        await callback.message.edit_text(text + suffix, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text + suffix, reply_markup=keyboard)
    await callback.answer()


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
