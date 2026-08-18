"""Покупка / продление / устройства подписки — см. §7, §8, §9.2, §9.3, §9.5
clone-architecture.md.

Бизнес-логика вынесена в отдельные async-функции (не привязанные к aiogram
Update/CallbackQuery), чтобы их можно было дергать напрямую из тестового
скрипта: ``get_active_tariff``, ``purchase_or_renew_subscription``,
``format_subscription_summary``, ``remove_user_device``, ``reset_user_devices``.

One-tap connect (§8) — упрощённая тестовая версия, без полноценного
get_subscription_page_config (это часть Mini App, отдельный этап): кнопка
"Подключить VPN" — inline-URL-кнопка с deep-link'ом `happ://add/<url>` (plain-режим
Happ, см. §8 clone-architecture.md). ВАЖНО: официально Telegram Bot API разрешает
для InlineKeyboardButton.url только http(s):// и tg:// схемы — happ:// официально
не документирована. Часть клиентов Telegram всё равно её открывает (как показано
в референсе — системный диалог "Открыть приложение?"), но Telegram может отклонить
отправку сообщения ошибкой BUTTON_URL_INVALID. На этот случай — авто-откат на
callback-кнопку, показывающую ссылку текстом (см. _send_subscription_view).

"Скопировать ключ" — нативная copy_text-кнопка (Bot API 7.5+, без похода на
сервер бота: Telegram сам копирует текст в буфер обмена по нажатию).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    WebAppInfo,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Payment, Subscription, Tariff, Transaction, User
from app.emoji import CALENDAR, CHART, CRYPTO, EXPIRED, GLOBE, HOURGLASS, MONEY, SBP, STARS, SUCCESS
from app.external.remnawave import get_remnawave_client
from app.keyboards.main_menu import CB_SUBSCRIPTION_MY, CB_SUBSCRIPTION_RENEW, back_to_menu_button
from app.services.notification_service import notify_payment_success
from app.services.payment import get_payment_provider
from app.services.referral_service import credit_referral_earning
from app.states import PurchaseStates

logger = logging.getLogger(__name__)

router = Router(name='subscription')

# Порядок и состав — см. диалог/референс-скрин: Карты и СБП (Platega, основной
# провайдер) -> Криптовалюта -> Telegram Stars. "↗" в подписи — визуальная
# параллель с референсом (там это настоящая внешняя ссылка на оплату; у нас
# пока stub, ссылки может не быть, но паритет вида сохраняем).
PAYMENT_METHODS: dict[str, str] = {
    'platega': '🏦 Карты и СБП',
    'cryptobot': '🪙 Криптовалюта',
    'stars': '⭐️ Telegram Stars',
}
# Те же способы оплаты, но с custom_emoji_id (см. app/emoji.py) — используется
# ТОЛЬКО в тексте сообщений (подтверждение выбора), НЕ в кнопках (kb_payment_methods
# ниже использует PAYMENT_METHODS с plain-эмодзи — Bot API не поддерживает
# custom emoji в тексте inline-кнопок).
PAYMENT_METHODS_RICH: dict[str, str] = {
    'platega': f'{SBP} Карты и СБП',
    'cryptobot': f'{CRYPTO} Криптовалюта',
    'stars': f'{STARS} Telegram Stars',
}

# Период хранится в БД как количество дней (30/90/180/360), но отображается
# пользователю в месяцах — см. референс ("1 месяц"/"3 месяца"/...). 24-месячного
# периода у нас никогда не было — резать нечего, диапазон уже 1/3/6/12 мес.
PERIOD_LABELS: dict[str, str] = {
    '30': '1 месяц',
    '90': '3 месяца',
    '180': '6 месяцев',
    '360': '12 месяцев',
}


def _format_price(amount_kopeks: int, method: str) -> str:
    """Цена в валюте способа оплаты — см. диалог: экран показывает ₽/$ /★ сразу
    в кнопке. Конвертация в $ и ★ приблизительная (settings.USD_RATE_KOPEKS /
    STARS_RATE_KOPEKS) — только для отображения, см. комментарий в app/config.py."""
    if method == 'cryptobot':
        usd = amount_kopeks / settings.USD_RATE_KOPEKS
        return f'${usd:.1f}'
    if method == 'stars':
        stars = max(1, round(amount_kopeks / settings.STARS_RATE_KOPEKS))
        return f'★{stars}'
    return f'{amount_kopeks / 100:.0f} ₽'


# === Бизнес-логика (тестируется без Update/CallbackQuery) ===================


async def get_active_tariffs(db: AsyncSession) -> list[Tariff]:
    result = await db.execute(select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id))
    return list(result.scalars().all())


async def get_active_tariff(db: AsyncSession) -> Tariff | None:
    """Первый активный тариф — используется там, где выбор тарифа не нужен
    (например devices-флоу оперирует уже существующей подпиской, не создаёт новую)."""
    tariffs = await get_active_tariffs(db)
    return tariffs[0] if tariffs else None


async def get_user_subscription(db: AsyncSession, user_id: int) -> Subscription | None:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    return result.scalar_one_or_none()


async def purchase_or_renew_subscription(
    db: AsyncSession,
    db_user: User,
    tariff: Tariff,
    period_days: int,
    method: str,
    bot: Bot | None = None,
) -> Subscription | None:
    """Оплата (сразу успешна в stub-режиме) + create/extend в Remnawave + запись
    Subscription/Transaction/Payment. См. §9.2/§9.3.

    Архитектурное решение (не описано явно в документе, принято тут): если у
    пользователя УЖЕ есть строка Subscription (активная или истёкшая) —
    используем extend_user_expiration + enable_user, а НЕ create_user заново.
    remnawave_uuid у существующей подписки остаётся валидным (панель просто
    отключает пользователя при истечении, не удаляет) — создание нового юзера
    в Remnawave потеряло бы историю/статистику на стороне панели и оставило бы
    мусорный отключённый профиль. create_user вызывается только при первой
    покупке (Subscription ещё не существует).

    Дата отсчёта продления: если подписка ещё активна (end_date > now) —
    продлеваем ОТ end_date (стандартная практика, не теряем оплаченные дни).
    Если истекла — продлеваем от now (не начисляем дни "в минус").
    """
    price_key = str(period_days)
    if price_key not in tariff.period_prices_kopeks:
        raise ValueError(f'Тариф {tariff.name} не имеет цены для периода {period_days} дней')
    amount_kopeks = int(tariff.period_prices_kopeks[price_key])

    provider = get_payment_provider(method)
    description = f'Подписка «{tariff.name}» на {period_days} дн.'
    created = await provider.create_payment(user_id=db_user.id, amount_kopeks=amount_kopeks, description=description)

    payment_success = created.status == 'success'

    transaction = Transaction(
        user_id=db_user.id,
        type='subscription_payment',
        amount_kopeks=amount_kopeks,
        status='completed' if payment_success else 'pending',
        description=description,
    )
    db.add(transaction)
    await db.flush()

    payment = Payment(
        user_id=db_user.id,
        transaction_id=transaction.id,
        provider=method,
        external_id=created.external_id,
        amount_kopeks=amount_kopeks,
        status='success' if payment_success else 'pending',
        raw_payload={},
    )
    db.add(payment)
    await db.flush()

    if not payment_success:
        # В stub-режиме это не должно происходить (create_payment всегда success).
        # Реальный провайдер создаёт платёж как pending — подписку не выдаём сразу,
        # сохраняем контекст в raw_payload, чтобы payment_poll_loop доделал выдачу
        # после подтверждения (см. app/services/payment_finalization.py).
        payment.raw_payload = {
            'kind': 'subscription',
            'tariff_id': tariff.id,
            'period_days': period_days,
            'payment_url': created.payment_url,
        }
        await db.flush()
        return None

    client = get_remnawave_client()
    now = datetime.now(timezone.utc)

    subscription = await get_user_subscription(db, db_user.id)

    if subscription is None:
        rw_user = await client.create_user(
            telegram_id=db_user.telegram_id,
            squad_uuids=tariff.squad_uuids,
            traffic_limit_gb=tariff.traffic_limit_gb,
            expire_at=now + timedelta(days=period_days),
        )
        db_user.remnawave_uuid = rw_user.uuid
        subscription = Subscription(
            user_id=db_user.id,
            tariff_id=tariff.id,
            status='active',
            start_date=now,
            end_date=now + timedelta(days=period_days),
            traffic_limit_gb=tariff.traffic_limit_gb,
            traffic_used_gb=0,
            device_limit=tariff.device_limit,
            subscription_url=rw_user.subscription_url,
            short_uuid=rw_user.short_uuid,
        )
        db.add(subscription)
    else:
        base = subscription.end_date
        if base is not None and base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        if subscription.status != 'active' or base is None or base <= now:
            base = now
        new_end = base + timedelta(days=period_days)

        assert db_user.remnawave_uuid is not None, 'Subscription существует, но remnawave_uuid отсутствует'
        rw_user = await client.extend_user_expiration(remnawave_uuid=db_user.remnawave_uuid, expire_at=new_end)
        await client.enable_user(remnawave_uuid=db_user.remnawave_uuid)

        subscription.end_date = new_end
        subscription.status = 'active'
        subscription.tariff_id = tariff.id
        # Баг, пойманный при добавлении мультитарифов: если пользователь продлевает
        # подписку ВЫБРАВ ДРУГОЙ тариф (напр. Онлайн -> Семейный), лимиты обязаны
        # смениться вместе с tariff_id — раньше (при единственном тарифе) это было
        # недостижимо, поэтому не проявлялось.
        subscription.device_limit = tariff.device_limit
        subscription.traffic_limit_gb = tariff.traffic_limit_gb
        subscription.reminder_3d_sent = False
        subscription.reminder_1d_sent = False
        if rw_user.subscription_url:
            subscription.subscription_url = rw_user.subscription_url
        if rw_user.short_uuid:
            subscription.short_uuid = rw_user.short_uuid

    await db.flush()

    try:
        await credit_referral_earning(db, payment)
    except Exception:
        logger.exception('credit_referral_earning упал (не блокирует оплату подписки)')

    if bot is not None:
        try:
            await notify_payment_success(
                bot, telegram_id=db_user.telegram_id, amount_kopeks=amount_kopeks, description=description
            )
        except Exception:
            logger.exception('notify_payment_success упал (не блокирует оплату подписки)')

    return subscription


async def remove_user_device(remnawave_uuid: str, hwid: str) -> None:
    client = get_remnawave_client()
    await client.remove_device(remnawave_uuid=remnawave_uuid, hwid=hwid)


async def reset_user_devices(remnawave_uuid: str) -> None:
    client = get_remnawave_client()
    await client.reset_user_devices(remnawave_uuid=remnawave_uuid)


def _format_time_left(end_date: datetime) -> str:
    """'3 дня, 14 часов, 27 минут' — компактная разбивка остатка, а не просто дата."""
    end = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
    delta = end - datetime.now(timezone.utc)
    if delta.total_seconds() <= 0:
        return '0 минут'

    total_minutes = int(delta.total_seconds() // 60)
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)

    parts = []
    if days:
        parts.append(f'{days} дн.')
    if hours or days:
        parts.append(f'{hours} ч.')
    parts.append(f'{minutes} мин.')
    return ' '.join(parts)


def format_subscription_summary(subscription: Subscription | None, balance_kopeks: int) -> str:
    """Компактная карточка в разметке Rich Message (Bot API 10.1) — <h2>/<blockquote>
    подтверждены живым тестом на реальном боте (см. диалог), не выдумано по документации.
    Результат — HTML для InputRichMessage(html=...), НЕ для обычного parse_mode=HTML
    (используйте через _send_subscription_view/_show_main_menu, не как text= напрямую).

    Баланс, время до конца подписки, трафик — см. диалог ('сократим инфу'). Полный
    статус/устройства/тариф намеренно не дублируются здесь — они доступны через
    кнопку «Устройства» и не нужны на этом экране.

    Иконки — через app/emoji.py (Emoji.html()): пока custom_id не задан, рендерится
    обычный unicode-fallback (текущее видимое поведение не меняется), см. диалог
    про кастомные премиум-эмодзи."""
    balance_line = f'<p>{MONEY} Баланс: <b>{balance_kopeks / 100:.2f} ₽</b></p>'

    if subscription is None:
        return f'<h2>{GLOBE} Подписка не оформлена</h2>{balance_line}'

    if subscription.status != 'active' or not subscription.end_date:
        end_date_str = subscription.end_date.strftime('%d.%m.%Y') if subscription.end_date else '—'
        return f'<h2>{EXPIRED} Подписка истекла</h2><p>{end_date_str}</p>{balance_line}'

    traffic_limit = '∞' if subscription.traffic_limit_gb == 0 else str(subscription.traffic_limit_gb)
    end_date_str = subscription.end_date.strftime('%d.%m.%Y')

    return (
        f'<h2>{GLOBE} Моя подписка</h2>'
        f'<blockquote>{HOURGLASS} Осталось: <b>{_format_time_left(subscription.end_date)}</b></blockquote>'
        f'<p>{CALENDAR} До {end_date_str}</p>'
        f'<p>{CHART} Трафик: <b>{subscription.traffic_used_gb:.1f} / {traffic_limit} ГБ</b></p>'
        f'{balance_line}'
    )


# === Клавиатуры ===============================================================


def kb_no_subscription() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💎 Купить подписку', callback_data='sub:buy')],
            [back_to_menu_button()],
        ]
    )


COPY_TEXT_MAX_LENGTH = 256  # ограничение Telegram Bot API для CopyTextButton.text


def kb_subscription_active(subscription_url: str | None, *, use_deep_link: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if settings.MINIAPP_URL:
        # Гарантированно ведём пользователя в Mini App для подключения (см.
        # диалог) — пока MINIAPP_URL не задан (нет https-домена), остаётся
        # прежний прямой happ://-fallback ниже, чтобы не сломать кнопку.
        rows.append(
            [InlineKeyboardButton(text='🔌 Подключить VPN', web_app=WebAppInfo(url=settings.MINIAPP_URL))]
        )
    elif subscription_url and use_deep_link:
        rows.append(
            [InlineKeyboardButton(text='🔌 Подключить VPN', url=f'happ://add/{subscription_url}')]
        )
    else:
        rows.append([InlineKeyboardButton(text='🔌 Подключить VPN', callback_data='sub:connect')])

    if subscription_url and len(subscription_url) <= COPY_TEXT_MAX_LENGTH:
        rows.append(
            [InlineKeyboardButton(text='📋 Скопировать ключ', copy_text=CopyTextButton(text=subscription_url))]
        )
    else:
        rows.append([InlineKeyboardButton(text='📋 Скопировать ключ', callback_data='sub:connect')])

    rows.append([InlineKeyboardButton(text='💎 Продлить подписку', callback_data=CB_SUBSCRIPTION_RENEW)])
    rows.append([InlineKeyboardButton(text='📱 Устройства', callback_data='sub:devices')])
    rows.append([back_to_menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_back_to_subscription() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text='⬅️ Назад', callback_data=CB_SUBSCRIPTION_MY)]]
    )


def kb_tariffs(tariffs: list[Tariff]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f'📦 {t.name}', callback_data=f'sub:tariff:{t.id}')] for t in tariffs]
    rows.append([InlineKeyboardButton(text='❌ Отмена', callback_data='sub:cancel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_periods(tariff: Tariff) -> InlineKeyboardMarkup:
    """Сетка 2 в ряд, без цены на самой кнопке — цена появляется на следующем
    экране (выбор способа оплаты), как в референсе."""
    periods = sorted(tariff.period_prices_kopeks.keys(), key=int)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for days_str in periods:
        label = PERIOD_LABELS.get(days_str, f'{days_str} дней')
        row.append(InlineKeyboardButton(text=label, callback_data=f'sub:period:{days_str}'))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text='❌ Отмена', callback_data='sub:cancel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_payment_methods(amount_kopeks: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f'{label} · {_format_price(amount_kopeks, name)} ↗', callback_data=f'sub:method:{name}')]
        for name, label in PAYMENT_METHODS.items()
    ]
    rows.append([InlineKeyboardButton(text='❌ Отмена', callback_data='sub:cancel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='✅ Подтвердить', callback_data='sub:confirm')],
            [InlineKeyboardButton(text='❌ Отмена', callback_data='sub:cancel')],
        ]
    )


def kb_devices(devices: list, remnawave_uuid: str) -> InlineKeyboardMarkup:
    rows = []
    for device in devices:
        label = device.device_model or device.platform or device.hwid
        rows.append(
            [InlineKeyboardButton(text=f'❌ {label}', callback_data=f'sub:devices:remove:{device.hwid}')]
        )
    rows.append([InlineKeyboardButton(text='🔄 Сбросить все', callback_data='sub:devices:reset')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=CB_SUBSCRIPTION_MY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_devices_reset_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Да, сбросить', callback_data='sub:devices:reset:yes')],
            [InlineKeyboardButton(text='Отмена', callback_data='sub:devices:reset:no')],
        ]
    )


def _is_invalid_button_url_error(exc: TelegramBadRequest) -> bool:
    """Telegram формулирует эту ошибку по-разному в зависимости от причины —
    подтверждено вживую: реальный текст оказался 'Unsupported URL protocol',
    а не 'BUTTON_URL_INVALID', как в документации/старых версиях API. Поэтому
    матчим по набору известных фраз, а не по одной константе."""
    message = str(exc).lower()
    return 'button url' in message and ('invalid' in message or 'protocol' in message or 'unsupported' in message)


# Подтверждено вживую: конкретный Bot API-сервер, к которому мы стучимся, отклоняет
# happ:// в url-кнопке ("Unsupported URL protocol"). Как только это случилось один раз —
# бессмысленно повторять заведомо провальный запрос на каждый рендер экрана подписки,
# поэтому запоминаем результат на время жизни процесса (сбрасывается перезапуском —
# если Telegram когда-нибудь начнёт разрешать кастомные схемы, поведение само подхватится).
_happ_deep_link_confirmed_unsupported = False


async def _send_subscription_view(callback: CallbackQuery, html: str, subscription_url: str | None) -> None:
    """edit_text(rich_message=...) с клавиатурой kb_subscription_active; если Telegram
    отклонил happ:// в url-кнопке, автоматически пересобирает клавиатуру без
    deep-link'а и повторяет попытку. `html` — разметка Rich Message (см.
    format_subscription_summary), а не обычный parse_mode=HTML текст."""
    global _happ_deep_link_confirmed_unsupported

    rich_message = InputRichMessage(html=html)

    if _happ_deep_link_confirmed_unsupported:
        await callback.message.edit_text(
            rich_message=rich_message, reply_markup=kb_subscription_active(subscription_url, use_deep_link=False)
        )
        return

    try:
        await callback.message.edit_text(rich_message=rich_message, reply_markup=kb_subscription_active(subscription_url))
    except TelegramBadRequest as exc:
        if not _is_invalid_button_url_error(exc):
            raise
        _happ_deep_link_confirmed_unsupported = True
        logger.warning(
            'Telegram отклонил happ:// deep-link в url-кнопке (%s) — откатываюсь на '
            'callback-кнопку с показом ссылки текстом и запоминаю это на весь процесс',
            exc,
        )
        await callback.message.edit_text(
            rich_message=rich_message, reply_markup=kb_subscription_active(subscription_url, use_deep_link=False)
        )


# === Хендлеры ==================================================================


@router.callback_query(lambda c: c.data == CB_SUBSCRIPTION_MY)
async def cb_subscription_my(callback: CallbackQuery, db: AsyncSession, db_user: User, state: FSMContext) -> None:
    await state.clear()
    subscription = await get_user_subscription(db, db_user.id)

    if subscription is None:
        html = format_subscription_summary(None, db_user.balance_kopeks)
        await callback.message.edit_text(rich_message=InputRichMessage(html=html), reply_markup=kb_no_subscription())
        await callback.answer()
        return

    text = format_subscription_summary(subscription, db_user.balance_kopeks)
    await _send_subscription_view(callback, text, subscription.subscription_url)
    await callback.answer()


@router.callback_query(lambda c: c.data == 'sub:connect')
async def cb_subscription_connect(callback: CallbackQuery, db: AsyncSession, db_user: User) -> None:
    subscription = await get_user_subscription(db, db_user.id)
    if subscription is None or not subscription.subscription_url:
        await callback.answer('Подписка не найдена', show_alert=True)
        return

    await callback.message.answer(
        f'Ваша ссылка подписки:\n\n<code>{subscription.subscription_url}</code>\n\n'
        f'Скопируйте её в приложение VPN-клиента.'
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == 'sub:devices')
async def cb_devices_list(callback: CallbackQuery, db_user: User) -> None:
    if not db_user.remnawave_uuid:
        await callback.answer('Подписка не найдена', show_alert=True)
        return

    client = get_remnawave_client()
    devices = await client.get_user_devices(remnawave_uuid=db_user.remnawave_uuid)

    if not devices:
        text = 'Устройства не подключены.'
    else:
        lines = [f'• {d.device_model or d.platform or d.hwid}' for d in devices]
        text = 'Ваши устройства:\n\n' + '\n'.join(lines)

    await callback.message.edit_text(text, reply_markup=kb_devices(devices, db_user.remnawave_uuid))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('sub:devices:remove:'))
async def cb_device_remove(callback: CallbackQuery, db_user: User) -> None:
    if not db_user.remnawave_uuid:
        await callback.answer('Подписка не найдена', show_alert=True)
        return

    hwid = callback.data.split('sub:devices:remove:', 1)[1]
    await remove_user_device(db_user.remnawave_uuid, hwid)
    await callback.answer('Устройство удалено')
    await cb_devices_list(callback, db_user)


@router.callback_query(lambda c: c.data == 'sub:devices:reset')
async def cb_devices_reset_ask(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        'Сбросить все подключённые устройства?', reply_markup=kb_devices_reset_confirm()
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == 'sub:devices:reset:yes')
async def cb_devices_reset_yes(callback: CallbackQuery, db_user: User) -> None:
    if db_user.remnawave_uuid:
        await reset_user_devices(db_user.remnawave_uuid)
    await callback.answer('Устройства сброшены')
    await cb_devices_list(callback, db_user)


@router.callback_query(lambda c: c.data == 'sub:devices:reset:no')
async def cb_devices_reset_no(callback: CallbackQuery, db_user: User) -> None:
    await callback.answer('Отменено')
    await cb_devices_list(callback, db_user)


# --- Покупка/продление FSM ---------------------------------------------------


async def _show_period_selection(callback: CallbackQuery, state: FSMContext, tariff: Tariff) -> None:
    await state.set_state(PurchaseStates.choosing_period)
    await state.update_data(tariff_id=tariff.id)
    await callback.message.edit_text(f'📦 <b>{tariff.name}</b>\n\nВыберите период подписки:', reply_markup=kb_periods(tariff))
    await callback.answer()


async def _start_purchase_flow(callback: CallbackQuery, db: AsyncSession, state: FSMContext) -> None:
    tariffs = await get_active_tariffs(db)
    if not tariffs:
        await callback.answer('Тариф временно недоступен', show_alert=True)
        return

    if len(tariffs) == 1:
        await _show_period_selection(callback, state, tariffs[0])
        return

    await state.set_state(PurchaseStates.choosing_tariff)
    await callback.message.edit_text('Выберите тариф:', reply_markup=kb_tariffs(tariffs))
    await callback.answer()


@router.callback_query(StateFilter(PurchaseStates.choosing_tariff), lambda c: c.data and c.data.startswith('sub:tariff:'))
async def cb_choose_tariff(callback: CallbackQuery, db: AsyncSession, state: FSMContext) -> None:
    tariff_id = int(callback.data.split('sub:tariff:', 1)[1])
    tariff = await db.get(Tariff, tariff_id)
    if tariff is None or not tariff.is_active:
        await callback.answer('Тариф недоступен', show_alert=True)
        return
    await _show_period_selection(callback, state, tariff)


@router.callback_query(lambda c: c.data == 'sub:buy')
async def cb_sub_buy(callback: CallbackQuery, db: AsyncSession, state: FSMContext) -> None:
    await _start_purchase_flow(callback, db, state)


@router.callback_query(lambda c: c.data == CB_SUBSCRIPTION_RENEW)
async def cb_sub_renew(callback: CallbackQuery, db: AsyncSession, state: FSMContext) -> None:
    await _start_purchase_flow(callback, db, state)


@router.callback_query(StateFilter(PurchaseStates.choosing_period), lambda c: c.data and c.data.startswith('sub:period:'))
async def cb_choose_period(callback: CallbackQuery, db: AsyncSession, state: FSMContext) -> None:
    days = callback.data.split('sub:period:', 1)[1]
    data = await state.update_data(period_days=int(days))

    tariff = await db.get(Tariff, data['tariff_id'])
    if tariff is None:
        await callback.answer('Тариф недоступен', show_alert=True)
        await state.clear()
        return
    amount_kopeks = int(tariff.period_prices_kopeks[days])

    await state.set_state(PurchaseStates.choosing_payment_method)
    label = PERIOD_LABELS.get(days, f'{days} дней')
    await callback.message.edit_text(
        f'📦 <b>{tariff.name} · {label}</b>\n\nВыберите удобный способ оплаты:',
        reply_markup=kb_payment_methods(amount_kopeks),
    )
    await callback.answer()


@router.callback_query(StateFilter(PurchaseStates.choosing_payment_method), lambda c: c.data and c.data.startswith('sub:method:'))
async def cb_choose_method(callback: CallbackQuery, db: AsyncSession, state: FSMContext) -> None:
    method = callback.data.split('sub:method:', 1)[1]
    data = await state.update_data(method=method)

    tariff = await db.get(Tariff, data['tariff_id'])
    if tariff is None:
        await callback.answer('Тариф недоступен', show_alert=True)
        await state.clear()
        return

    period_days = data['period_days']
    price_kopeks = int(tariff.period_prices_kopeks[str(period_days)])
    await state.set_state(PurchaseStates.confirming)

    label = PERIOD_LABELS.get(str(period_days), f'{period_days} дней')
    text = (
        f'<b>Подтверждение оплаты</b>\n\n'
        f'Тариф: {tariff.name}\n'
        f'Период: {label}\n'
        f'Способ оплаты: {PAYMENT_METHODS_RICH.get(method, method)}\n'
        f'Сумма: {_format_price(price_kopeks, method)}'
    )
    await callback.message.edit_text(text, reply_markup=kb_confirm())
    await callback.answer()


@router.callback_query(StateFilter(PurchaseStates.confirming), lambda c: c.data == 'sub:confirm')
async def cb_confirm_purchase(
    callback: CallbackQuery, db: AsyncSession, db_user: User, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    tariff = await db.get(Tariff, data['tariff_id'])
    if tariff is None:
        await callback.answer('Тариф недоступен', show_alert=True)
        await state.clear()
        return

    try:
        subscription = await purchase_or_renew_subscription(
            db, db_user, tariff, period_days=data['period_days'], method=data['method'], bot=bot
        )
    except Exception:
        logger.exception('Ошибка оформления подписки')
        await callback.answer('Не удалось оформить подписку, попробуйте позже', show_alert=True)
        await state.clear()
        return

    await state.clear()

    if subscription is None:
        # Реальный провайдер — платёж создан, но ещё не подтверждён (см.
        # purchase_or_renew_subscription). Подписка будет выдана автоматически
        # после подтверждения (payment_poll_loop), пользователь получит уведомление.
        result = await db.execute(
            select(Payment)
            .where(Payment.user_id == db_user.id, Payment.status == 'pending')
            .order_by(Payment.id.desc())
            .limit(1)
        )
        payment = result.scalar_one_or_none()
        payment_url = (payment.raw_payload or {}).get('payment_url') if payment else None

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=(
                [[InlineKeyboardButton(text='💳 Перейти к оплате', url=payment_url)]] if payment_url else []
            )
            + [[back_to_menu_button()]]
        )
        await callback.message.edit_text(
            'Платёж создан, но ещё не подтверждён. Перейдите по ссылке для оплаты — '
            'подписка будет выдана автоматически после подтверждения платежа.',
            reply_markup=keyboard,
        )
        await callback.answer()
        return

    text = f'<p>{SUCCESS} <b>Оплата прошла успешно!</b></p>' + format_subscription_summary(subscription, db_user.balance_kopeks)
    await _send_subscription_view(callback, text, subscription.subscription_url)
    await callback.answer()


@router.callback_query(lambda c: c.data == 'sub:cancel')
async def cb_cancel_purchase(callback: CallbackQuery, db: AsyncSession, db_user: User, state: FSMContext) -> None:
    """Отмена покупки/продления — всегда в главное меню, а не назад в карточку
    подписки: пользователь явно жмёт "Отмена" на любом шаге мастера (тариф/период/
    способ оплаты/подтверждение), и ожидает выйти из процесса целиком."""
    from app.handlers.start import cb_menu_main

    await cb_menu_main(callback, db, db_user, state)


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
