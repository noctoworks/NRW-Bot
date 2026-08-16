"""«Подарить подписку» — выбор периода/способа оплаты, создание GiftCode. См. §9.4
clone-architecture.md. Активация подарка получателем (redeem_gift_code) — в
handlers/start.py (deep-link /start gift_CODE), не здесь.
"""

from __future__ import annotations

import logging

from aiogram import Dispatcher, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Payment, Tariff, Transaction, User
from app.keyboards.main_menu import CB_GIFT_MENU, back_to_menu_button
from app.services.gift_service import create_gift_code
from app.services.payment import get_payment_provider
from app.states import GiftStates

logger = logging.getLogger(__name__)

router = Router(name='gift')

PAYMENT_METHODS = [
    ('stars', '⭐️ Telegram Stars'),
    ('yookassa', '🏦 СБП (Платега)'),
    ('cryptobot', '🪙 Криптовалюта'),
]


TEXTS = {
    'ru': {
        'not_registered': 'Сначала выполните /start.',
        'no_tariff': '⚠️ Сейчас нет доступного тарифа для подарка. Попробуйте позже.',
        'choose_period': '🎁 Кому периоду подарить подписку?',
        'choose_payment': 'Выберите способ оплаты ({price:.2f} ₽):',
        'payment_pending': (
            'Платёж создан, но не завершён автоматически (провайдер {provider}). '
            'Перейдите по ссылке для оплаты:\n{url}'
        ),
        'success': (
            '🎉 Подарочный код создан!\n\n'
            'Отправьте эту ссылку тому, кому хотите подарить подписку:\n'
            '<code>{link}</code>\n\n'
            'Код действителен 30 дней.'
        ),
        'cancelled': 'Отменено.',
    },
    'en': {
        'not_registered': 'Please run /start first.',
        'no_tariff': '⚠️ No tariff available for a gift right now. Try again later.',
        'choose_period': '🎁 Which period would you like to gift?',
        'choose_payment': 'Choose a payment method ({price:.2f}):',
        'payment_pending': (
            'Payment created but not completed automatically (provider {provider}). '
            'Open the link to pay:\n{url}'
        ),
        'success': (
            '🎉 Gift code created!\n\n'
            'Send this link to the person you want to gift a subscription to:\n'
            '<code>{link}</code>\n\n'
            'The code is valid for 30 days.'
        ),
        'cancelled': 'Cancelled.',
    },
}


def _t(lang: str | None, key: str) -> str:
    return TEXTS.get(lang or 'ru', TEXTS['ru'])[key]


def _period_keyboard(tariff: Tariff) -> InlineKeyboardMarkup:
    rows = []
    for period_str, price_kopeks in sorted(tariff.period_prices_kopeks.items(), key=lambda kv: int(kv[0])):
        days = int(period_str)
        price = price_kopeks / 100
        rows.append(
            [InlineKeyboardButton(text=f'{days} дн. — {price:.2f} ₽', callback_data=f'gift:period:{days}')]
        )
    rows.append([back_to_menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _payment_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=f'gift:pay:{method}')] for method, title in PAYMENT_METHODS]
    rows.append([back_to_menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_or_answer(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await callback.message.answer(text, reply_markup=reply_markup)


async def _get_active_tariff(db: AsyncSession) -> Tariff | None:
    result = await db.execute(select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id).limit(1))
    return result.scalar_one_or_none()


@router.callback_query(F.data == CB_GIFT_MENU)
async def cb_gift_menu(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if db_user is None:
        await callback.answer()
        return
    lang = db_user.language

    tariff = await _get_active_tariff(db)
    if tariff is None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
        await _edit_or_answer(callback, _t(lang, 'no_tariff'), keyboard)
        await callback.answer()
        return

    await state.update_data(tariff_id=tariff.id)
    await state.set_state(GiftStates.choosing_period)
    await _edit_or_answer(callback, _t(lang, 'choose_period'), _period_keyboard(tariff))
    await callback.answer()


@router.callback_query(GiftStates.choosing_period, F.data.startswith('gift:period:'))
async def cb_choose_period(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if db_user is None:
        await callback.answer()
        return
    lang = db_user.language
    days = int(callback.data.split(':')[-1])

    data = await state.get_data()
    tariff_result = await db.execute(select(Tariff).where(Tariff.id == data.get('tariff_id')))
    tariff = tariff_result.scalar_one_or_none()
    if tariff is None or str(days) not in tariff.period_prices_kopeks:
        await callback.answer()
        return

    price = tariff.period_prices_kopeks[str(days)] / 100
    await state.update_data(period_days=days)
    await state.set_state(GiftStates.choosing_payment_method)
    await _edit_or_answer(callback, _t(lang, 'choose_payment').format(price=price), _payment_keyboard())
    await callback.answer()


@router.callback_query(GiftStates.choosing_payment_method, F.data.startswith('gift:pay:'))
async def cb_choose_payment(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if db_user is None:
        await callback.answer()
        return
    lang = db_user.language
    method = callback.data.split(':')[-1]

    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    period_days = data.get('period_days')

    tariff_result = await db.execute(select(Tariff).where(Tariff.id == tariff_id))
    tariff = tariff_result.scalar_one_or_none()
    if tariff is None or period_days is None or str(period_days) not in tariff.period_prices_kopeks:
        await state.clear()
        await callback.answer()
        return

    amount_kopeks = tariff.period_prices_kopeks[str(period_days)]

    provider = get_payment_provider(method)
    created = await provider.create_payment(
        user_id=db_user.id,
        amount_kopeks=amount_kopeks,
        description=f'Подарок подписки на {period_days} дн. ({tariff.name})',
    )

    if created.status != 'success':
        await state.clear()
        if created.payment_url:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
            await _edit_or_answer(
                callback,
                _t(lang, 'payment_pending').format(provider=method, url=created.payment_url),
                keyboard,
            )
        await callback.answer()
        return

    transaction = Transaction(
        user_id=db_user.id,
        type='gift',
        amount_kopeks=amount_kopeks,
        status='completed',
        description=f'Подарок подписки на {period_days} дн.',
    )
    db.add(transaction)
    await db.flush()

    db.add(
        Payment(
            user_id=db_user.id,
            transaction_id=transaction.id,
            provider=method,
            external_id=created.external_id,
            amount_kopeks=amount_kopeks,
            status='success',
        )
    )

    gift_code = await create_gift_code(db, tariff=tariff, period_days=period_days, gifter=db_user)
    await state.clear()

    bot_username = settings.BOT_USERNAME or '<укажите_BOT_USERNAME>'
    link = f'https://t.me/{bot_username}?start=gift_{gift_code.code}'

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    await _edit_or_answer(callback, _t(lang, 'success').format(link=link), keyboard)
    await callback.answer()


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
