"""Регистрация, /start, deep-link (ref_/gift_), главное меню — см. §9.1/§9.4
clone-architecture.md.

Флоу:
    /start [ref_CODE|gift_CODE]
        -> если db_user is None: язык -> правила -> INSERT User (тут же
           применяется ref_CODE, если валиден) -> (если был gift_CODE)
           redeem_gift_code -> главное меню
        -> если db_user уже есть: (если был gift_CODE) redeem_gift_code
           -> главное меню

В клоне нет гостевых лендингов/phantom-user — без активной подписки просто
показываем меню, остальные разделы (subscription/gift/referral/support)
владеют своими callback'ами самостоятельно.
"""

from __future__ import annotations

import logging

from aiogram import Dispatcher, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputRichMessage, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.keyboards.main_menu import (
    CB_INFO_ABOUT,
    CB_MENU_MAIN,
    CB_SETTINGS_MENU,
    back_to_menu_button,
    get_main_menu_keyboard,
)
from app.services.gift_service import GiftCodeError, redeem_gift_code
from app.services.referral_service import generate_referral_code
from app.states import RegistrationStates

logger = logging.getLogger(__name__)

router = Router(name='start')


TEXTS = {
    'ru': {
        'choose_language': 'Привет! Выберите язык интерфейса:',
        'rules': (
            'Прежде чем продолжить — примите условия использования сервиса.\n\n'
            'Нажимая «Принимаю», вы соглашаетесь с правилами использования бота.'
        ),
        'accept_rules': '✅ Принимаю',
        'welcome': 'Добро пожаловать! Это меню сервиса — выберите нужный раздел.',
        'welcome_back': 'С возвращением! Выберите нужный раздел.',
        'about': (
            'Это сервис доступа к VPN по подписке.\n\n'
            'Здесь вы можете купить или продлить подписку, подарить её другу, '
            'приглашать друзей за бонусы и получать поддержку — всё через это меню.'
        ),
        'settings': 'Настройки. Текущий язык: {lang}. Выберите новый:',
        'settings_saved': 'Язык интерфейса обновлён.',
        'gift_success': '🎉 Подарочная подписка активирована! Загляните в «Моя подписка», чтобы увидеть детали.',
        'gift_error': '⚠️ Не удалось активировать подарочный код: {error}',
        'gift_not_ready': '⚠️ Активация подарочных кодов временно недоступна, попробуйте позже.',
        'back': '⬅️ Назад',
    },
    'en': {
        'choose_language': 'Hi! Please choose your interface language:',
        'rules': (
            'Before we continue — please accept the terms of service.\n\n'
            'By tapping "Accept" you agree to the bot usage rules.'
        ),
        'accept_rules': '✅ Accept',
        'welcome': 'Welcome! This is the service menu — pick a section.',
        'welcome_back': 'Welcome back! Pick a section.',
        'about': (
            'This is a subscription-based VPN access service.\n\n'
            'Here you can buy or renew a subscription, gift it to a friend, '
            'invite friends for bonuses and get support — all from this menu.'
        ),
        'settings': 'Settings. Current language: {lang}. Choose a new one:',
        'settings_saved': 'Interface language updated.',
        'gift_success': '🎉 Gift subscription activated! Check "My subscription" for details.',
        'gift_error': '⚠️ Could not redeem the gift code: {error}',
        'gift_not_ready': '⚠️ Gift code redemption is temporarily unavailable, please try again later.',
        'back': '⬅️ Back',
    },
}


def _t(lang: str | None, key: str) -> str:
    return TEXTS.get(lang or 'ru', TEXTS['ru'])[key]


def _language_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='🇷🇺 Русский', callback_data=f'{prefix}:ru'),
                InlineKeyboardButton(text='🇬🇧 English', callback_data=f'{prefix}:en'),
            ]
        ]
    )


def _rules_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_t(lang, 'accept_rules'), callback_data='reg:accept')],
        ]
    )


def _parse_payload(args: str | None) -> tuple[str | None, str | None, str | None]:
    """Возвращает (ref_code, gift_code, campaign_param) — deep-link payload
    после /start. Кампания (Фаза 4) — единственный вариант БЕЗ префикса: наши
    ref_/gift_ ссылки всегда с явным префиксом, поэтому голый payload
    однозначно трактуется как start_parameter кампании, коллизий нет."""
    if not args:
        return None, None, None
    if args.startswith('ref_'):
        code = args[len('ref_') :].strip()
        return (code or None), None, None
    if args.startswith('gift_'):
        code = args[len('gift_') :].strip()
        return None, (code or None), None
    return None, None, (args.strip() or None)


async def _generate_unique_referral_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = generate_referral_code()
        result = await db.execute(select(User.id).where(User.referral_code == code))
        if result.scalar_one_or_none() is None:
            return code
    raise RuntimeError('Не удалось сгенерировать уникальный referral_code за 10 попыток')


async def _apply_gift_payload(message_or_cq: Message | CallbackQuery, db: AsyncSession, db_user: User, gift_code: str) -> None:
    lang = db_user.language
    try:
        await redeem_gift_code(db, code=gift_code, recipient=db_user)
    except GiftCodeError as exc:
        text = _t(lang, 'gift_error').format(error=str(exc))
        await _answer(message_or_cq, text)
        return
    except NotImplementedError:
        logger.warning('redeem_gift_code ещё не реализован (параллельная разработка gift_service)')
        await _answer(message_or_cq, _t(lang, 'gift_not_ready'))
        return
    await _answer(message_or_cq, _t(lang, 'gift_success'))


async def _answer(target: Message | CallbackQuery, text: str) -> None:
    if isinstance(target, CallbackQuery):
        await target.message.answer(text)
    else:
        await target.answer(text)


async def _edit_or_answer(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Редактирует текущее сообщение вместо отправки нового — везде, где переход
    инициирован callback'ом (нажатием кнопки). Отправка нового сообщения уместна
    только в ответ на текстовый ввод пользователя (там нечего редактировать) или
    когда контент должен остаться отдельным (например ссылка подписки для копирования).

    Fallback на answer(), если edit_text невозможен (например текст не изменился —
    Telegram вернёт "message is not modified", или исходное сообщение было удалено).
    """
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await callback.message.answer(text, reply_markup=reply_markup)


async def _edit_or_answer_rich(
    callback: CallbackQuery, html: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Rich-вариант _edit_or_answer (Bot API 10.1, sendRichMessage/editMessageText.rich_message —
    подтверждено живым тестом, см. диалог). `html` — Rich Message разметка (<h2>/<blockquote>/...),
    НЕ обычный parse_mode=HTML текст — их нельзя смешивать в одном вызове."""
    rich_message = InputRichMessage(html=html)
    try:
        await callback.message.edit_text(rich_message=rich_message, reply_markup=reply_markup)
    except Exception:
        await callback.message.answer_rich(rich_message=rich_message, reply_markup=reply_markup)


async def _show_main_menu(target: Message | CallbackQuery, db: AsyncSession, db_user: User, *, is_new: bool) -> None:
    if is_new:
        # Только что зарегистрировался — подписки/баланса ещё нет, показываем
        # обычный приветственный текст, а не пустую карточку.
        text = _t(db_user.language, 'welcome')
        if isinstance(target, CallbackQuery):
            await _edit_or_answer(target, text, get_main_menu_keyboard(is_admin=db_user.is_admin))
        else:
            await target.answer(text, reply_markup=get_main_menu_keyboard(is_admin=db_user.is_admin))
        return

    # Уже зарегистрированный пользователь возвращается в меню — вместо общей фразы
    # "С возвращением!" сразу показываем короткую rich-карточку по аккаунту
    # (баланс/время до конца подписки/трафик), см. диалог: "сократим инфу".
    from app.handlers.subscription import format_subscription_summary, get_user_subscription

    subscription = await get_user_subscription(db, db_user.id)
    html = format_subscription_summary(subscription, db_user.balance_kopeks)

    if isinstance(target, CallbackQuery):
        await _edit_or_answer_rich(target, html, get_main_menu_keyboard(is_admin=db_user.is_admin))
    else:
        await target.answer_rich(rich_message=InputRichMessage(html=html), reply_markup=get_main_menu_keyboard(is_admin=db_user.is_admin))


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    ref_code, gift_code, campaign_param = _parse_payload(command.args)

    if db_user is None:
        await state.update_data(ref_code=ref_code, gift_code=gift_code, campaign_param=campaign_param)
        await state.set_state(RegistrationStates.choosing_language)
        await message.answer(_t('ru', 'choose_language'), reply_markup=_language_keyboard('reg:lang'))
        return

    if gift_code:
        await _apply_gift_payload(message, db, db_user, gift_code)

    await _show_main_menu(message, db, db_user, is_new=False)


@router.callback_query(RegistrationStates.choosing_language, F.data.startswith('reg:lang:'))
async def cb_choose_language(callback: CallbackQuery, state: FSMContext) -> None:
    lang = callback.data.split(':')[-1]
    if lang not in TEXTS:
        lang = 'ru'
    await state.update_data(language=lang)
    await state.set_state(RegistrationStates.accepting_rules)
    await callback.message.edit_text(_t(lang, 'rules'), reply_markup=_rules_keyboard(lang))
    await callback.answer()


@router.callback_query(RegistrationStates.accepting_rules, F.data == 'reg:accept')
async def cb_accept_rules(callback: CallbackQuery, db: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get('language', 'ru')
    ref_code = data.get('ref_code')
    gift_code = data.get('gift_code')
    campaign_param = data.get('campaign_param')

    telegram_user = callback.from_user
    referred_by_id: int | None = None
    if ref_code:
        result = await db.execute(select(User).where(User.referral_code == ref_code))
        referrer = result.scalar_one_or_none()
        if referrer is not None and referrer.telegram_id != telegram_user.id:
            referred_by_id = referrer.id

    referral_code = await _generate_unique_referral_code(db)

    new_user = User(
        telegram_id=telegram_user.id,
        username=telegram_user.username,
        language=lang,
        referral_code=referral_code,
        referred_by_id=referred_by_id,
    )
    db.add(new_user)
    await db.flush()

    await state.clear()

    if gift_code:
        await _apply_gift_payload(callback, db, new_user, gift_code)

    if campaign_param:
        from app.services.campaign_service import apply_campaign_bonus, get_campaign_by_start_parameter

        campaign = await get_campaign_by_start_parameter(db, campaign_param)
        if campaign is not None:
            await apply_campaign_bonus(db, campaign=campaign, user=new_user)

    await callback.message.edit_reply_markup(reply_markup=None)
    await _show_main_menu(callback, db, new_user, is_new=True)

    # Предложение бесплатного пробного периода (Фаза 3, см. диалог) — отдельным
    # сообщением следом за меню, а не автовыдачей: пользователь должен явно
    # согласиться, чтобы не "сжигать" триал незаметно для него.
    from app.handlers.subscription import get_active_tariff, get_user_subscription

    tariff = await get_active_tariff(db)
    if tariff and tariff.trial_enabled and not new_user.trial_used and await get_user_subscription(db, new_user.id) is None:
        trial_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f'🎁 Попробовать {tariff.trial_period_days} дн. бесплатно', callback_data='trial:start')]
            ]
        )
        await callback.message.answer('Хотите попробовать сервис бесплатно?', reply_markup=trial_keyboard)

    await callback.answer()


@router.callback_query(F.data == 'trial:start')
async def cb_start_trial(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if db_user is None:
        await callback.answer()
        return
    if db_user.trial_used:
        await callback.answer('Пробный период уже использован', show_alert=True)
        return

    from app.handlers.subscription import get_active_tariff, get_user_subscription
    from app.services.subscription_provisioning import provision_or_extend_subscription

    tariff = await get_active_tariff(db)
    if tariff is None or not tariff.trial_enabled:
        await callback.answer('Пробный период недоступен', show_alert=True)
        return
    if await get_user_subscription(db, db_user.id) is not None:
        await callback.answer('У вас уже есть подписка', show_alert=True)
        return

    await provision_or_extend_subscription(db, user=db_user, tariff=tariff, period_days=tariff.trial_period_days)
    db_user.trial_used = True
    await db.flush()

    await callback.message.edit_text(f'🎉 Пробный период на {tariff.trial_period_days} дн. активирован! Загляните в «Моя подписка».')
    await callback.answer()


@router.callback_query(F.data == CB_INFO_ABOUT)
async def cb_info_about(callback: CallbackQuery, db_user: User | None) -> None:
    lang = db_user.language if db_user else 'ru'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    await _edit_or_answer(callback, _t(lang, 'about'), keyboard)
    await callback.answer()


@router.callback_query(F.data == CB_SETTINGS_MENU)
async def cb_settings_menu(callback: CallbackQuery, db_user: User | None) -> None:
    lang = db_user.language if db_user else 'ru'
    keyboard = _language_keyboard('settings:lang')
    keyboard.inline_keyboard.append([back_to_menu_button()])
    await _edit_or_answer(callback, _t(lang, 'settings').format(lang=lang), keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith('settings:lang:'))
async def cb_settings_set_language(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if db_user is None:
        await callback.answer()
        return
    lang = callback.data.split(':')[-1]
    if lang not in TEXTS:
        lang = 'ru'
    db_user.language = lang
    await db.flush()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    await _edit_or_answer(callback, _t(lang, 'settings_saved'), keyboard)
    await callback.answer()


@router.callback_query(F.data == CB_MENU_MAIN)
async def cb_menu_main(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    """Единая точка возврата в главное меню — на неё ссылаются кнопки «В меню»
    из ВСЕХ остальных модулей (subscription.py и т.д.), см. app/keyboards/main_menu.py.
    """
    await state.clear()
    if db_user is None:
        await callback.answer()
        return
    await _show_main_menu(callback, db, db_user, is_new=False)
    await callback.answer()


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
