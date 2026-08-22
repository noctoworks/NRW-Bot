"""«Подарить подписку» — выбор периода/способа оплаты, создание GiftCode. См. §9.4
clone-architecture.md. Активация подарка получателем (redeem_gift_code) — в
handlers/start.py (deep-link /start gift_CODE), не здесь.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import GiftCode, Payment, Tariff, Transaction, User
from app.emoji import icon_button
from app.handlers.subscription import PAYMENT_METHOD_ICONS, PAYMENT_METHOD_LABELS
from app.keyboards.main_menu import CB_GIFT_MENU, back_to_menu_button
from app.services.gift_service import create_gift_code
from app.services.payment import get_payment_provider
from app.services.pricing_service import apply_discount, get_discount_percent, get_period_price_kopeks
from app.services.referral_service import credit_referral_earning
from app.states import GiftStates

logger = logging.getLogger(__name__)

router = Router(name='gift')

# Тот же набор способов оплаты, что и в handlers/subscription.py — иконки и
# подписи берутся оттуда (единый источник), чтобы не рассинхронизировать два
# списка при смене custom_emoji_id (см. app/emoji.py).
PAYMENT_METHODS = [
    (name, f'{PAYMENT_METHOD_ICONS[name].fallback} {label}') for name, label in PAYMENT_METHOD_LABELS.items()
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


def _period_keyboard(tariff: Tariff, discount_percent: int = 0) -> InlineKeyboardMarkup:
    rows = []
    for period_str, price_kopeks in sorted(tariff.period_prices_kopeks.items(), key=lambda kv: int(kv[0])):
        days = int(period_str)
        price = apply_discount(price_kopeks, discount_percent) / 100
        rows.append(
            [InlineKeyboardButton(text=f'{days} дн. — {price:.2f} ₽', callback_data=f'gift:period:{days}')]
        )
    rows.append([back_to_menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _payment_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [icon_button(label, PAYMENT_METHOD_ICONS[name], callback_data=f'gift:pay:{name}')]
        for name, label in PAYMENT_METHOD_LABELS.items()
    ]
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


async def purchase_gift_subscription(
    db: AsyncSession, db_user: User, tariff: Tariff, period_days: int, method: str, bot: Bot | None = None
) -> GiftCode | None:
    """Оплата + создание GiftCode — тот же паттерн, что и
    handlers/subscription.py::purchase_or_renew_subscription (в т.ч. то же
    решение с флешем Payment/Transaction ДО прихода ответа платёжного
    провайдера). Возвращает None, если реальный провайдер вернул платёж как
    pending — тогда GiftCode будет создан позже payment_finalization.py
    после подтверждения (см. payment_poll_loop). Переиспользуется и ботом
    (cb_choose_payment), и /cabinet/gift/purchase — бизнес-логика не
    дублируется на два места.

    ВАЖНО (см. диалог/ревью про handlers/subscription.py): если это упадёт
    ПОСЛЕ флеша Payment(status='success') — например create_gift_code не
    сумеет сгенерировать уникальный код — caller ОБЯЗАН явно откатить сессию
    (db.rollback()) в except-блоке, если он гасит исключение сам, а не
    пробрасывает наружу. AuthMiddleware/get_db коммитят сессию безусловно
    после успешного возврата хендлера/роута.
    """
    amount_kopeks = await get_period_price_kopeks(db, tariff, period_days, db_user)
    description = f'Подарок подписки на {period_days} дн. ({tariff.name})'

    provider = get_payment_provider(method)
    created = await provider.create_payment(
        user_id=db_user.id, amount_kopeks=amount_kopeks, description=description, bot=bot, telegram_id=db_user.telegram_id
    )

    if created.status != 'success':
        # Реальный провайдер — платёж создан, но не подтверждён сразу. Сохраняем
        # контекст в raw_payload, чтобы payment_poll_loop доделал выдачу подарочного
        # кода после подтверждения (см. app/services/payment_finalization.py).
        transaction = Transaction(
            user_id=db_user.id, type='gift', amount_kopeks=amount_kopeks, status='pending', description=description
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
                status='pending',
                raw_payload={
                    'kind': 'gift',
                    'tariff_id': tariff.id,
                    'period_days': period_days,
                    'payment_url': created.payment_url,
                },
            )
        )
        await db.flush()
        return None

    transaction = Transaction(
        user_id=db_user.id, type='gift', amount_kopeks=amount_kopeks, status='completed', description=description
    )
    db.add(transaction)
    await db.flush()

    payment = Payment(
        user_id=db_user.id,
        transaction_id=transaction.id,
        provider=method,
        external_id=created.external_id,
        amount_kopeks=amount_kopeks,
        status='success',
    )
    db.add(payment)
    await db.flush()

    gift_code = await create_gift_code(db, tariff=tariff, period_days=period_days, gifter=db_user)

    # Начисление рефереру покупателя — иначе комиссия капает только тем, чей
    # платёж прошёл через payment_finalization.py (реальный провайдер, pending),
    # а мгновенный успех (в т.ч. любой платёж в PAYMENTS_MODE=stub) остаётся без
    # комиссии — см. ревью, тот же паттерн, что в handlers/subscription.py.
    try:
        await credit_referral_earning(db, payment, bot=bot)
    except Exception:
        logger.exception('credit_referral_earning упал (не блокирует покупку подарка)')

    return gift_code


@router.callback_query(F.data == CB_GIFT_MENU)
async def cb_gift_menu(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if db_user is None:
        await callback.answer()
        return
    if db_user.is_blocked:
        await callback.answer('Ваш аккаунт заблокирован.', show_alert=True)
        return
    lang = db_user.language

    tariff = await _get_active_tariff(db)
    if tariff is None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
        await _edit_or_answer(callback, _t(lang, 'no_tariff'), keyboard)
        await callback.answer()
        return

    discount_percent = await get_discount_percent(db, db_user)
    await state.update_data(tariff_id=tariff.id)
    await state.set_state(GiftStates.choosing_period)
    await _edit_or_answer(callback, _t(lang, 'choose_period'), _period_keyboard(tariff, discount_percent))
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

    price = await get_period_price_kopeks(db, tariff, days, db_user) / 100
    await state.update_data(period_days=days)
    await state.set_state(GiftStates.choosing_payment_method)
    await _edit_or_answer(callback, _t(lang, 'choose_payment').format(price=price), _payment_keyboard())
    await callback.answer()


@router.callback_query(GiftStates.choosing_payment_method, F.data.startswith('gift:pay:'))
async def cb_choose_payment(
    callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext, bot: Bot
) -> None:
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

    try:
        gift_code = await purchase_gift_subscription(db, db_user, tariff, period_days, method, bot=bot)
    except Exception:
        logger.exception('Ошибка оформления подарка')
        # См. handlers/subscription.py::cb_confirm_purchase — purchase_gift_subscription
        # уже мог успеть flush'нуть Payment(status='success') до сбоя (например
        # create_gift_code не сгенерировал уникальный код за 10 попыток); гася
        # исключение здесь вместо проброса наружу, обязаны откатить сессию сами —
        # иначе AuthMiddleware закоммитит "успешный" платёж без выданного подарка.
        await db.rollback()
        await state.clear()
        await callback.answer('Не удалось создать платёж, попробуйте позже', show_alert=True)
        return

    await state.clear()

    if gift_code is None:
        # Реальный провайдер — платёж создан, но не подтверждён сразу. Подарочный
        # код будет создан автоматически после подтверждения (payment_poll_loop).
        result = await db.execute(
            select(Payment)
            .where(Payment.user_id == db_user.id, Payment.status == 'pending')
            .order_by(Payment.id.desc())
            .limit(1)
        )
        payment = result.scalar_one_or_none()
        payment_url = (payment.raw_payload or {}).get('payment_url') if payment else None
        if payment_url:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
            await _edit_or_answer(
                callback, _t(lang, 'payment_pending').format(provider=method, url=payment_url), keyboard
            )
        await callback.answer()
        return

    bot_username = settings.BOT_USERNAME or '<укажите_BOT_USERNAME>'
    link = f'https://t.me/{bot_username}?start=gift_{gift_code.code}'

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    await _edit_or_answer(callback, _t(lang, 'success').format(link=link), keyboard)
    await callback.answer()


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
