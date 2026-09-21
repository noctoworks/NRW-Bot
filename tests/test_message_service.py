"""Сервис шаблонов: кэш, сохранение/сброс, отправка с откатом на заводской текст."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select

from app.config import settings
from app.database.models import MessageTemplate
from app.services.message_templates import service
from app.services.message_templates.registry import UnknownEventError, get_event
from app.services.message_templates.service import (
    Override,
    TemplateValidationError,
    build_preview,
    compose,
    get_overrides,
    invalidate_cache,
    is_template_error,
    render_message,
    reset_template,
    send_templated,
    send_test_message,
    update_template,
)
from tests.helpers import make_user

CHAT = 42
EXPIRED = get_event('subscription_expired')
PAYMENT = get_event('payment_success')


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(service, 'AsyncSessionLocal', session_factory)
    invalidate_cache()
    yield
    invalidate_cache()


def bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=SendMessage(chat_id=CHAT, text='x'), message=message)


async def _set(factory, key: str, **fields) -> None:
    async with factory() as db:
        db.add(MessageTemplate(key=key, **fields))
        await db.commit()
    invalidate_cache()


# --- compose (чистая функция) ---------------------------------------------------


def test_compose_default_when_no_override():
    rendered = compose(PAYMENT, None, {'amount': '10.00', 'description': 'X'})

    assert rendered.text == rendered.default_text == '✅ Оплата на сумму 10.00₽ прошла успешно. X'
    assert (rendered.enabled, rendered.is_custom, rendered.button_text) == (True, False, None)


def test_compose_custom_text_escapes_variables():
    override = Override('payment_success', '<b>{description}</b> — {amount}', None, True, None, None)

    rendered = compose(PAYMENT, override, {'amount': '1.00', 'description': '<i>&'})

    assert rendered.text == '<b>&lt;i&gt;&amp;</b> — 1.00'
    assert rendered.is_custom and rendered.default_text.startswith('✅ Оплата')


def test_compose_button_label_override_and_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'MINIAPP_URL', 'https://mini.example')
    winback = get_event('winback')

    default = compose(winback, None, {})
    custom = compose(winback, Override('winback', None, 'Вернуться', False, None, None), {})

    assert default.button_text == default.default_button_text == '💎 Возобновить подписку'
    assert custom.button_text == 'Вернуться' and custom.enabled is False
    assert custom.text == default.text and custom.is_custom is False  # текст не задан — заводской


def test_events_without_button_never_get_one():
    assert compose(EXPIRED, Override('subscription_expired', None, 'зря', True, None, None), {}).button_text is None


# --- кэш ------------------------------------------------------------------------


def test_overrides_are_cached_until_ttl_and_invalidate(session_factory, monkeypatch):
    loads = []
    real_factory = session_factory

    def counting_factory():
        loads.append(1)
        return real_factory()

    monkeypatch.setattr(service, 'AsyncSessionLocal', counting_factory)

    async def scenario():
        await _set(session_factory, 'winback', template='Привет')
        first = await get_overrides(now=1000.0)
        await get_overrides(now=1000.0 + 59)  # в пределах TTL — из кэша
        assert len(loads) == 1
        await get_overrides(now=1000.0 + 61)  # TTL истёк — перечитали
        assert len(loads) == 2
        invalidate_cache()
        await get_overrides(now=1000.0 + 62)
        assert len(loads) == 3
        assert first['winback'].template == 'Привет'

    asyncio.run(scenario())


def test_load_failure_returns_stale_cache_or_empty(monkeypatch):
    async def scenario():
        assert await get_overrides(now=1.0) == {}
        monkeypatch.setattr(service, 'AsyncSessionLocal', lambda: (_ for _ in ()).throw(RuntimeError('db down')))
        assert await get_overrides(now=1000.0) == {}  # первой загрузки не было — пусто, но без исключения

    asyncio.run(scenario())


def test_load_failure_keeps_previous_cache(session_factory, monkeypatch):
    async def scenario():
        await _set(session_factory, 'winback', template='Старый')
        assert (await get_overrides(now=1.0))['winback'].template == 'Старый'
        monkeypatch.setattr(service, 'AsyncSessionLocal', lambda: (_ for _ in ()).throw(RuntimeError('db down')))

        assert (await get_overrides(now=1000.0))['winback'].template == 'Старый'

    asyncio.run(scenario())


# --- сохранение и сброс ---------------------------------------------------------


def test_update_validates_and_saves_with_author(session_factory):
    async def scenario():
        admin = await make_user(session_factory, is_admin=True)
        async with session_factory() as db:
            with pytest.raises(TemplateValidationError) as caught:
                await update_template(db, 'payment_success', admin_user_id=admin, template='<script>x</script> {nope}')
            assert len(caught.value.errors) >= 2
            await update_template(db, 'payment_success', admin_user_id=admin, template='Оплачено: {amount}₽')
            await db.commit()

        async with session_factory() as db:
            row = await db.get(MessageTemplate, 'payment_success')
            assert (row.template, row.enabled, row.updated_by_user_id) == ('Оплачено: {amount}₽', True, admin)
        assert (await get_overrides())['payment_success'].template == 'Оплачено: {amount}₽'  # кэш сброшен после коммита

    asyncio.run(scenario())


def test_cache_is_refreshed_only_after_commit(session_factory):
    """Пока запись не закоммичена, другие читатели её не видят — кэш нельзя сбрасывать раньше коммита
    (иначе он тут же закэшировал бы старое). После коммита кэш обновляется сразу."""

    async def scenario():
        assert await get_overrides() == {}  # кэш заполнен пустым
        async with session_factory() as db:
            await update_template(db, 'winback', admin_user_id=None, enabled=False)
            assert await get_overrides() == {}  # не закоммичено: старое значение ещё актуально для читателей
            await db.commit()
        assert (await get_overrides())['winback'].enabled is False

    asyncio.run(scenario())


def test_partial_updates_do_not_touch_other_fields(session_factory):
    async def scenario():
        async with session_factory() as db:
            await update_template(db, 'winback', admin_user_id=None, enabled=False)
            await update_template(db, 'winback', admin_user_id=None, button_text='Вернуться')
            await db.commit()
        async with session_factory() as db:
            row = await db.get(MessageTemplate, 'winback')
            assert (row.template, row.button_text, row.enabled) == (None, 'Вернуться', False)
            await update_template(db, 'winback', admin_user_id=None, template='Привет!')
            await update_template(db, 'winback', admin_user_id=None, template=None)  # вернуть заводской текст
            await db.commit()
            assert (await db.get(MessageTemplate, 'winback')).template is None

    asyncio.run(scenario())


def test_update_rejects_bad_button_and_unknown_event(session_factory):
    async def scenario():
        async with session_factory() as db:
            with pytest.raises(TemplateValidationError):
                await update_template(db, 'winback', admin_user_id=None, button_text='<b>x</b>')
            with pytest.raises(TemplateValidationError):
                await update_template(db, 'subscription_expired', admin_user_id=None, button_text='кнопки нет')
            with pytest.raises(UnknownEventError):
                await update_template(db, 'no_such', admin_user_id=None, template='x')

    asyncio.run(scenario())


def test_reset_deletes_the_row_and_reports_it(session_factory):
    async def scenario():
        await _set(session_factory, 'winback', template='Привет', enabled=False)
        async with session_factory() as db:
            assert await reset_template(db, 'winback') is True
            assert await reset_template(db, 'winback') is False
            await db.commit()
        async with session_factory() as db:
            assert (await db.execute(select(MessageTemplate))).scalars().all() == []
        assert await get_overrides() == {}
        with pytest.raises(UnknownEventError):
            async with session_factory() as db:
                await reset_template(db, 'no_such')

    asyncio.run(scenario())


# --- отправка -------------------------------------------------------------------


def test_default_text_is_sent_when_nothing_is_customised():
    bot = AsyncMock()

    asyncio.run(send_templated(bot, telegram_id=CHAT, key='subscription_expired'))

    bot.send_message.assert_awaited_once_with(chat_id=CHAT, text='❌ Ваша подписка истекла. Продлите её в главном меню.', reply_markup=None)


def test_custom_text_is_sent(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'payment_success', template='<b>Спасибо!</b> {amount}₽ — {description}')
        await send_templated(bot, telegram_id=CHAT, key='payment_success', amount='5.00', description='A&B')

    asyncio.run(scenario())

    assert bot.send_message.await_args.kwargs['text'] == '<b>Спасибо!</b> 5.00₽ — A&amp;B'


def test_disabled_event_sends_nothing(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'winback', enabled=False)
        await send_templated(bot, telegram_id=CHAT, key='winback')

    asyncio.run(scenario())

    bot.send_message.assert_not_awaited()


def test_template_error_falls_back_to_default_exactly_once(session_factory):
    bot = AsyncMock()
    bot.send_message.side_effect = [bad_request("Bad Request: can't parse entities: unsupported start tag"), None]

    async def scenario():
        await _set(session_factory, 'subscription_expired', template='<b>сломано')
        await send_templated(bot, telegram_id=CHAT, key='subscription_expired')

    asyncio.run(scenario())

    assert bot.send_message.await_count == 2
    first, second = (call.kwargs['text'] for call in bot.send_message.await_args_list)
    assert first == '<b>сломано' and second == '❌ Ваша подписка истекла. Продлите её в главном меню.'


def test_invalid_custom_emoji_falls_back(session_factory):
    bot = AsyncMock()
    bot.send_message.side_effect = [bad_request('Bad Request: ENTITY_TEXT_INVALID'), None]

    async def scenario():
        await _set(session_factory, 'subscription_expired', template='<tg-emoji emoji-id="1">🏦</tg-emoji> конец')
        await send_templated(bot, telegram_id=CHAT, key='subscription_expired')

    asyncio.run(scenario())

    assert bot.send_message.await_count == 2


def test_unrelated_bad_request_does_not_trigger_fallback(session_factory):
    bot = AsyncMock()
    bot.send_message.side_effect = bad_request('Bad Request: chat not found')

    async def scenario():
        await _set(session_factory, 'subscription_expired', template='Свой текст')
        await send_templated(bot, telegram_id=CHAT, key='subscription_expired')  # не должно бросать

    asyncio.run(scenario())

    assert bot.send_message.await_count == 1


def test_uncustomised_message_is_not_resent_on_template_like_error():
    """Заводской текст не «виноват» — повторная отправка того же самого бессмысленна."""
    bot = AsyncMock()
    bot.send_message.side_effect = bad_request("can't parse entities")

    asyncio.run(send_templated(bot, telegram_id=CHAT, key='subscription_expired'))

    assert bot.send_message.await_count == 1


def test_failed_fallback_is_swallowed(session_factory):
    bot = AsyncMock()
    bot.send_message.side_effect = bad_request("can't parse entities")

    async def scenario():
        await _set(session_factory, 'subscription_expired', template='<b>x')
        await send_templated(bot, telegram_id=CHAT, key='subscription_expired')

    asyncio.run(scenario())

    assert bot.send_message.await_count == 2


def test_default_send_failure_never_raises():
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError('telegram down')

    asyncio.run(send_templated(bot, telegram_id=CHAT, key='subscription_expired'))


def test_flood_control_is_retried_once(monkeypatch):
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(service.asyncio, 'sleep', fake_sleep)
    bot = AsyncMock()
    bot.send_message.side_effect = [TelegramRetryAfter(method=SendMessage(chat_id=CHAT, text='x'), message='flood', retry_after=3), None]

    asyncio.run(send_templated(bot, telegram_id=CHAT, key='subscription_expired'))

    assert bot.send_message.await_count == 2 and slept == [4]


def test_custom_button_label_is_used_in_the_keyboard(session_factory, monkeypatch):
    monkeypatch.setattr(settings, 'MINIAPP_URL', 'https://mini.example')
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'winback', button_text='Вернуться')
        await send_templated(bot, telegram_id=CHAT, key='winback')

    asyncio.run(scenario())

    button = bot.send_message.await_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.text == 'Вернуться' and button.web_app.url.startswith('https://mini.example/payment')


def test_is_template_error_markers():
    assert is_template_error(bad_request("Bad Request: can't parse entities: x"))
    assert is_template_error(bad_request('Bad Request: ENTITY_TEXT_INVALID'))
    assert is_template_error(bad_request('RICH_MESSAGE_EMOJI_INVALID'))
    assert is_template_error(bad_request('Bad Request: message is too long'))
    assert not is_template_error(bad_request('Bad Request: chat not found'))


# --- предпросмотр и тестовая отправка ---------------------------------------------


def test_preview_uses_example_variables_and_overrides():
    current = asyncio.run(build_preview('payment_success'))
    changed = asyncio.run(build_preview('payment_success', template='{amount}₽'))

    assert current.text == '✅ Оплата на сумму 249.00₽ прошла успешно. Подписка «Онлайн» на 30 дн.'
    assert changed.text == '249.00₽' and changed.is_custom


def test_send_test_message_sends_preview_and_propagates_telegram_errors():
    bot = AsyncMock()

    asyncio.run(send_test_message(bot, telegram_id=CHAT, key='payment_success', template='Тест {amount}'))
    assert bot.send_message.await_args.kwargs['text'] == 'Тест 249.00'

    bot.send_message.side_effect = bad_request("can't parse entities")
    with pytest.raises(TelegramBadRequest):
        asyncio.run(send_test_message(bot, telegram_id=CHAT, key='payment_success', template='<b>x'))


def test_render_message_reads_overrides(session_factory):
    async def scenario():
        await _set(session_factory, 'referral_bonus', template='Плюс {amount}')
        return await render_message('referral_bonus', amount='7.00')

    assert asyncio.run(scenario()).text == 'Плюс 7.00'
