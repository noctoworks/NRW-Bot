"""Активация промокода — команда `/promo` (текстовая, вне главного меню, см. задание
в PROGRESS.md: не трогаем чужую клавиатуру main_menu.py). См. §9.7 clone-architecture.md.
"""

from __future__ import annotations

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.keyboards.main_menu import back_to_menu_button
from app.services.promocode_service import PromoCodeError, PromoCodeResult, activate_promocode
from app.states import PromoCodeStates

router = Router(name='promocode')

# Callback-точка входа (в дополнение к команде /promo) — нужна кнопке "Промокод"
# в конструкторе кнопок рассылки (см. admin.py, перенесено из Bedolaga: там это
# 'menu_promocode'), т.к. inline-кнопка не может вызвать текстовую команду.
CB_PROMO_ENTER = 'promo:enter'


TEXTS = {
    'ru': {
        'not_registered': 'Сначала выполните /start.',
        'enter_code': '🎟 Введите промокод одним сообщением (например SUMMER2026):',
        'error': '⚠️ Не удалось активировать промокод: {error}',
        'success_balance': '✅ Промокод активирован! На баланс начислено {amount:.2f} ₽.',
        'success_days': '✅ Промокод активирован! Подписка продлена на {days} дн.',
    },
    'en': {
        'not_registered': 'Please run /start first.',
        'enter_code': '🎟 Enter your promo code in a single message (e.g. SUMMER2026):',
        'error': '⚠️ Could not activate promo code: {error}',
        'success_balance': '✅ Promo code activated! {amount:.2f} credited to your balance.',
        'success_days': '✅ Promo code activated! Subscription extended by {days} day(s).',
    },
}


def _t(lang: str | None, key: str) -> str:
    return TEXTS.get(lang or 'ru', TEXTS['ru'])[key]


@router.message(Command('promo'))
async def cmd_promo(message: Message, state: FSMContext, db_user: User | None) -> None:
    lang = db_user.language if db_user else 'ru'
    if db_user is None:
        await message.answer(_t(lang, 'not_registered'))
        return
    if db_user.is_blocked:
        await message.answer('Ваш аккаунт заблокирован.')
        return
    await state.set_state(PromoCodeStates.entering_code)
    await message.answer(_t(lang, 'enter_code'))


@router.callback_query(F.data == CB_PROMO_ENTER)
async def cb_promo_enter(callback: CallbackQuery, state: FSMContext, db_user: User | None) -> None:
    lang = db_user.language if db_user else 'ru'
    if db_user is None:
        await callback.answer()
        return
    if db_user.is_blocked:
        await callback.answer('Ваш аккаунт заблокирован.', show_alert=True)
        return
    await state.set_state(PromoCodeStates.entering_code)
    await callback.message.answer(_t(lang, 'enter_code'))
    await callback.answer()


@router.message(PromoCodeStates.entering_code, F.text)
async def process_promo_code(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    await state.clear()
    if db_user is None:
        return
    if db_user.is_blocked:
        await message.answer('Ваш аккаунт заблокирован.')
        return
    lang = db_user.language
    code = message.text.strip()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])

    try:
        result: PromoCodeResult = await activate_promocode(db, code=code, user=db_user)
    except PromoCodeError as exc:
        await message.answer(_t(lang, 'error').format(error=str(exc)), reply_markup=keyboard)
        return

    if result.type == 'balance':
        await message.answer(_t(lang, 'success_balance').format(amount=result.value / 100), reply_markup=keyboard)
    else:
        await message.answer(_t(lang, 'success_days').format(days=result.value), reply_markup=keyboard)


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
