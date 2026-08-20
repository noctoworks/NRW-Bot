"""Поддержка — пересылка сообщений пользователь -> админ и обратно (reply-роутинг).
См. §9.8 clone-architecture.md.

MVP-решение: сообщение пользователя пересылается ВСЕМ settings.admin_ids(), но
admin_message_id (для роутинга ответа) сохраняется только для сообщения,
отправленного ПЕРВОМУ админу из множества. Если админов несколько — отвечать
на тикет реплаем сможет только первый в списке ADMIN_TELEGRAM_IDS; остальные
видят сообщение, но их reply не будет доставлен пользователю. Для расширения
до full multi-admin роутинга потребовалась бы отдельная таблица
(admin_telegram_id, admin_message_id) на каждое пересланное сообщение — вне
объёма MVP, см. отчёт агента.
"""

from __future__ import annotations

import html
import logging

from aiogram import Dispatcher, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import SupportMessage, User
from app.keyboards.main_menu import CB_SUPPORT_MENU, back_to_menu_button
from app.states import SupportStates

logger = logging.getLogger(__name__)

router = Router(name='support')


@router.callback_query(F.data == CB_SUPPORT_MENU)
async def cb_support_menu(callback: CallbackQuery, state: FSMContext, db_user: User | None) -> None:
    if db_user is None:
        await callback.answer()
        return
    if db_user.is_blocked:
        await callback.answer('Ваш аккаунт заблокирован.', show_alert=True)
        return
    await state.set_state(SupportStates.writing_message)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    try:
        await callback.message.edit_text(
            '✍️ Опишите вашу проблему одним сообщением — мы передадим её администратору.',
            reply_markup=keyboard,
        )
    except Exception:
        await callback.message.answer(
            '✍️ Опишите вашу проблему одним сообщением — мы передадим её администратору.',
            reply_markup=keyboard,
        )
    await callback.answer()


@router.message(SupportStates.writing_message, F.text)
async def on_support_message(message: Message, state: FSMContext, db: AsyncSession, db_user: User | None) -> None:
    if db_user is None:
        await state.clear()
        return
    if db_user.is_blocked:
        await message.answer('Ваш аккаунт заблокирован.')
        await state.clear()
        return

    text = message.text
    support_msg = SupportMessage(user_id=db_user.id, direction='in', body=text)
    db.add(support_msg)
    await db.flush()

    admin_ids = sorted(settings.admin_ids())
    # Бот отправляет с parse_mode=HTML по умолчанию (см. app/bot.py) — текст
    # юзера и username подставляются как есть, любой '<'/'&' в сообщении ломал
    # парсинг у ВСЕХ админов разом (TelegramBadRequest), тикет терялся молча —
    # см. ревью. html.escape() делает подстановку безопасной независимо от
    # parse_mode.
    username = html.escape(db_user.username) if db_user.username else '—'
    header = f'📩 Сообщение от @{username} (id {db_user.telegram_id}):\n\n{html.escape(text)}'

    first_admin_message_id: int | None = None
    for admin_id in admin_ids:
        try:
            sent = await message.bot.send_message(admin_id, header)
        except Exception:
            logger.warning('Не удалось переслать сообщение поддержки админу %s', admin_id, exc_info=True)
            continue
        if first_admin_message_id is None:
            first_admin_message_id = sent.message_id

    if first_admin_message_id is not None:
        support_msg.admin_message_id = first_admin_message_id
        await db.flush()

    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    if first_admin_message_id is None:
        # Ни один админ не получил сообщение — не врём "отправлено", иначе тикет
        # теряется молча, а юзер думает, что его услышали (см. ревью).
        await message.answer(
            '⚠️ Не удалось передать сообщение администратору. Попробуйте ещё раз чуть позже.',
            reply_markup=keyboard,
        )
        return
    await message.answer('✅ Сообщение отправлено администратору. Мы ответим здесь же.', reply_markup=keyboard)


@router.message(F.reply_to_message, F.text)
async def on_admin_reply(message: Message, db: AsyncSession) -> None:
    # F.reply_to_message matches ЛЮБОЕ реплай-сообщение админа, не только ответ
    # на тикет поддержки — например реплай на промпт FSM из admin.py (там нет
    # такого фильтра). Раньше это тихо "съедало" апдейт (return без SkipHandler),
    # и он не долетал до нужного хендлера в другом роутере, застревая — см.
    # ревью. SkipHandler явно говорит диспетчеру "это не моё, пробуй дальше".
    if message.from_user is None or message.from_user.id not in settings.admin_ids():
        raise SkipHandler

    reply_to_id = message.reply_to_message.message_id
    result = await db.execute(
        select(SupportMessage)
        .where(SupportMessage.admin_message_id == reply_to_id, SupportMessage.direction == 'in')
        .order_by(SupportMessage.id.desc())
    )
    support_msg = result.scalars().first()
    if support_msg is None:
        raise SkipHandler

    user = await db.get(User, support_msg.user_id)
    if user is None:
        return

    try:
        await message.bot.send_message(user.telegram_id, f'💬 Ответ поддержки:\n\n{message.text}')
    except Exception:
        logger.warning('Не удалось доставить ответ поддержки пользователю %s', user.telegram_id, exc_info=True)
        await message.answer('⚠️ Не удалось доставить ответ пользователю (возможно, заблокировал бота).')
        return

    reply_record = SupportMessage(user_id=user.id, direction='out', body=message.text)
    db.add(reply_record)
    await db.flush()
    await message.answer('✅ Ответ отправлен пользователю.')


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
