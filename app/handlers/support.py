"""Поддержка — тикеты с multi-admin роутингом. См. §9.8 clone-architecture.md и
диалог 2026-08-28 (редизайн из MVP-версии, где тред был неявной группировкой
SupportMessage по user_id, без статуса, и отвечать мог только первый админ
из ADMIN_TELEGRAM_IDS).

Устройство: SupportTicket (open/closed, assigned_admin_*) — один на переписку.
Сообщение юзера пересылается ВСЕМ settings.admin_ids(), и на КАЖДОГО заведена
своя SupportMessageDelivery (support_message_id, admin_telegram_id,
admin_message_id) — значит ответить реплаем может любой из них, не только
первый. Первый ответивший "застолбливает" тикет (assigned_admin_*) — это
информационная пометка для координации, не жёсткий лок, остальные всё равно
получают пересылку и могут ответить.

Продолжение диалога без повторного захода в меню: FSM-состояние
writing_message НЕ сбрасывается после отправки сообщения — юзер просто пишет
дальше в этот же чат. Оно сбрасывается только естественно, когда юзер сам
нажимает "В меню" (cb_menu_main, handlers/start.py). Тикет в БД при этом
остаётся open, и повторный заход в "Поддержка" находит и продолжает его же
(_get_or_create_open_ticket), не плодя дубликаты. Закрывает тикет только
админ, из MiniApp-админки (app/cabinet/admin_routes.py) — в боте кнопки
закрытия нет.
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
from app.database.models import SupportMessage, SupportMessageDelivery, SupportTicket, User
from app.keyboards.main_menu import CB_SUPPORT_MENU, back_to_menu_button
from app.states import SupportStates

logger = logging.getLogger(__name__)

router = Router(name='support')


async def _get_or_create_open_ticket(db: AsyncSession, db_user: User) -> SupportTicket:
    result = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == db_user.id, SupportTicket.status == 'open')
        .order_by(SupportTicket.id.desc())
    )
    ticket = result.scalars().first()
    if ticket is not None:
        return ticket
    ticket = SupportTicket(user_id=db_user.id)
    db.add(ticket)
    await db.flush()
    return ticket


@router.callback_query(F.data == CB_SUPPORT_MENU)
async def cb_support_menu(callback: CallbackQuery, state: FSMContext, db: AsyncSession, db_user: User | None) -> None:
    if db_user is None:
        await callback.answer()
        return
    if db_user.is_blocked:
        await callback.answer('Ваш аккаунт заблокирован.', show_alert=True)
        return
    await _get_or_create_open_ticket(db, db_user)
    await state.set_state(SupportStates.writing_message)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    text = (
        '✍️ Опишите вашу проблему — мы передадим её администратору. '
        'Дальше просто пишите сюда же, диалог останется открытым, пока вопрос не решится.'
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
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

    ticket = await _get_or_create_open_ticket(db, db_user)

    text = message.text
    support_msg = SupportMessage(ticket_id=ticket.id, user_id=db_user.id, direction='in', body=text)
    db.add(support_msg)
    await db.flush()

    admin_ids = sorted(settings.admin_ids())
    # Бот отправляет с parse_mode=HTML по умолчанию (см. app/bot.py) — текст
    # юзера и username подставляются как есть, любой '<'/'&' в сообщении ломал
    # парсинг у ВСЕХ админов разом (TelegramBadRequest), тикет терялся молча —
    # см. ревью. html.escape() делает подстановку безопасной независимо от
    # parse_mode.
    username = html.escape(db_user.username) if db_user.username else '—'
    assigned_note = f'\n🔒 Ведёт: {html.escape(ticket.assigned_admin_name)}' if ticket.assigned_admin_name else ''
    header = (
        f'📩 Тикет #{ticket.id} от @{username} (id {db_user.telegram_id}):{assigned_note}\n\n{html.escape(text)}'
    )

    delivered = False
    for admin_id in admin_ids:
        try:
            sent = await message.bot.send_message(admin_id, header)
        except Exception:
            logger.warning('Не удалось переслать сообщение поддержки админу %s', admin_id, exc_info=True)
            continue
        delivered = True
        db.add(
            SupportMessageDelivery(
                support_message_id=support_msg.id,
                admin_telegram_id=admin_id,
                admin_message_id=sent.message_id,
            )
        )
    await db.flush()

    # Состояние НЕ сбрасываем — юзер может сразу написать следующее сообщение
    # в этот же тикет, без повторного захода в меню (см. докстринг модуля).
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_to_menu_button()]])
    if not delivered:
        # Ни один админ не получил сообщение — не врём "отправлено", иначе тикет
        # теряется молча, а юзер думает, что его услышали (см. ревью).
        await message.answer(
            '⚠️ Не удалось передать сообщение администратору. Попробуйте ещё раз чуть позже.',
            reply_markup=keyboard,
        )
        return
    await message.answer(
        '✅ Сообщение отправлено администратору. Мы ответим здесь же — можете писать ещё.',
        reply_markup=keyboard,
    )


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
        select(SupportMessageDelivery, SupportMessage)
        .join(SupportMessage, SupportMessage.id == SupportMessageDelivery.support_message_id)
        .where(
            SupportMessageDelivery.admin_telegram_id == message.from_user.id,
            SupportMessageDelivery.admin_message_id == reply_to_id,
            SupportMessage.direction == 'in',
        )
        .order_by(SupportMessage.id.desc())
    )
    row = result.first()
    if row is None:
        raise SkipHandler
    _delivery, support_msg = row

    ticket = await db.get(SupportTicket, support_msg.ticket_id)
    if ticket is None:
        return
    user = await db.get(User, support_msg.user_id)
    if user is None:
        return

    try:
        await message.bot.send_message(user.telegram_id, f'💬 Ответ поддержки:\n\n{message.text}')
    except Exception:
        logger.warning('Не удалось доставить ответ поддержки пользователю %s', user.telegram_id, exc_info=True)
        await message.answer('⚠️ Не удалось доставить ответ пользователю (возможно, заблокировал бота).')
        return

    reply_record = SupportMessage(ticket_id=ticket.id, user_id=user.id, direction='out', body=message.text)
    db.add(reply_record)

    claim_note = ''
    if ticket.assigned_admin_id is None and ticket.assigned_admin_name is None:
        admin_user_result = await db.execute(select(User).where(User.telegram_id == message.from_user.id))
        admin_user = admin_user_result.scalars().first()
        if admin_user is not None:
            ticket.assigned_admin_id = admin_user.id
            ticket.assigned_admin_name = admin_user.username or str(admin_user.telegram_id)
        else:
            ticket.assigned_admin_name = message.from_user.username or str(message.from_user.id)
        claim_note = f' Тикет #{ticket.id} теперь ведёте вы.'

    await db.flush()
    await message.answer(f'✅ Ответ отправлен пользователю.{claim_note}')


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
