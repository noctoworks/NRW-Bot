"""Характеризационные тесты: тексты и клавиатуры автоматических сообщений остаются прежними.

Написаны ДО перехода на шаблоны и обязаны проходить и на старом коде, и на новом
(`send_templated`). Тексты скопированы из app/services/notification_service.py как есть."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.keyboards.main_menu import CB_SUBSCRIPTION_RENEW
from app.services import notification_service as ns

CHAT = 42

TEXT_CASES = [
    (
        'payment_success',
        lambda bot: ns.notify_payment_success(bot, telegram_id=CHAT, amount_kopeks=24900, description='Подписка «Онлайн» на 30 дн.'),
        '✅ Оплата на сумму 249.00₽ прошла успешно. Подписка «Онлайн» на 30 дн.',
    ),
    (
        'referral_bonus',
        lambda bot: ns.notify_referral_bonus(bot, telegram_id=CHAT, amount_kopeks=2500),
        '🎉 Вам начислено 25.00₽ реферальных бонусов!',
    ),
    (
        'referral_invite_bonus',
        lambda bot: ns.notify_referral_invite_bonus(bot, telegram_id=CHAT, bonus_days=3),
        '🚀 По вашей ссылке зарегистрировался друг — начислено +3 дн. подписки!\n\n'
        'Приглашайте ещё — бонус начисляется за каждого нового друга.',
    ),
    (
        'subscription_expiring',
        lambda bot: ns.notify_subscription_expiring(bot, telegram_id=CHAT, days_left=3),
        '⏳ Ваша подписка истекает через 3 дн.',
    ),
    (
        'subscription_expired',
        lambda bot: ns.notify_subscription_expired(bot, telegram_id=CHAT),
        '❌ Ваша подписка истекла. Продлите её в главном меню.',
    ),
    (
        'gift_redeemed (с username)',
        lambda bot: ns.notify_gift_redeemed_to_gifter(bot, gifter_telegram_id=CHAT, recipient_username='friend'),
        '🎁 Ваш подарок активировал @friend!',
    ),
    (
        'gift_redeemed (без username)',
        lambda bot: ns.notify_gift_redeemed_to_gifter(bot, gifter_telegram_id=CHAT, recipient_username=None),
        '🎁 Ваш подарок активировал пользователь!',
    ),
    (
        'gift_code_ready',
        lambda bot: ns.notify_gift_code_ready(bot, telegram_id=CHAT, link='https://t.me/nrw_bot?start=gift_ABC123'),
        '🎉 Оплата прошла успешно! Подарочный код создан.\n\n'
        'Отправьте эту ссылку тому, кому хотите подарить подписку:\n'
        'https://t.me/nrw_bot?start=gift_ABC123\n\n'
        'Код действителен 30 дней.',
    ),
    (
        'balance_credited',
        lambda bot: ns.notify_balance_changed(bot, telegram_id=CHAT, amount_kopeks=10000, new_balance_kopeks=35000),
        '💰 Баланс пополнен!\n\nСумма: +100.00₽\nТекущий баланс: 350.00₽',
    ),
    (
        'balance_debited',
        lambda bot: ns.notify_balance_changed(bot, telegram_id=CHAT, amount_kopeks=-5000, new_balance_kopeks=30000),
        '💸 Средства списаны с баланса\n\nСумма: -50.00₽\nТекущий баланс: 300.00₽',
    ),
    (
        'balance_zero_amount_is_treated_as_debit',  # крайний случай прежнего поведения: 0 идёт в ветку списания
        lambda bot: ns.notify_balance_changed(bot, telegram_id=CHAT, amount_kopeks=0, new_balance_kopeks=35000),
        '💸 Средства списаны с баланса\n\nСумма: -0.00₽\nТекущий баланс: 350.00₽',
    ),
    (
        'autopay_activated',
        lambda bot: ns.notify_autopay_activated(bot, telegram_id=CHAT),
        '🔄 Автоплатёж подключён — подписка будет продлеваться автоматически каждый месяц.',
    ),
    (
        'autopay_charge_failed',
        lambda bot: ns.notify_autopay_charge_failed(bot, telegram_id=CHAT),
        '⚠️ Не удалось списать автоплатёж — проверьте, что на карте/счёте достаточно средств.\n\n'
        'Подписка продолжает действовать до текущей даты окончания.',
    ),
    (
        'autopay_stopped',
        lambda bot: ns.notify_autopay_stopped(bot, telegram_id=CHAT),
        '🔕 Автоплатёж отключён (банк отклонил привязку или списания подряд не проходят).\n\n'
        'Подписку можно продлить вручную в любой момент.',
    ),
    (
        'winback',
        lambda bot: ns.notify_winback(bot, telegram_id=CHAT),
        '👋 Соскучились? Ваша подписка уже некоторое время неактивна — '
        'самое время вернуться, пока для вас держим ваш профиль и настройки.',
    ),
    (
        'abandoned_payment',
        lambda bot: ns.notify_abandoned_payment(bot, telegram_id=CHAT),
        '💳 Похоже, оплата не завершилась. Если передумали или что-то пошло не '
        'так — можно оформить заново, это займёт минуту.',
    ),
    (
        'welcome_nudge',
        lambda bot: ns.notify_welcome_nudge(bot, telegram_id=CHAT),
        '🔐 Не забыли про VPN? Пробный период уже начался — попробуйте подключиться '
        'сейчас, а когда пробный период закончится, сможете оформить подписку в один тап.',
    ),
]


def _send(call) -> AsyncMock:
    bot = AsyncMock()
    asyncio.run(call(bot))
    return bot


@pytest.mark.parametrize('name, call, expected', TEXT_CASES, ids=[case[0] for case in TEXT_CASES])
def test_text_is_unchanged(name, call, expected):
    bot = _send(call)

    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs['text'] == expected
    assert bot.send_message.await_args.kwargs['chat_id'] == CHAT


@pytest.mark.parametrize('name, call, expected', TEXT_CASES, ids=[case[0] for case in TEXT_CASES])
def test_send_call_shape(name, call, expected):
    """Вызов bot.send_message всегда keyword-only: chat_id, text, reply_markup (другие тесты на это опираются)."""
    bot = _send(call)

    assert set(bot.send_message.await_args.kwargs) == {'chat_id', 'text', 'reply_markup'}
    assert bot.send_message.await_args.args == ()


NO_BUTTON = [case for case in TEXT_CASES if case[0] not in ('winback', 'abandoned_payment', 'welcome_nudge')]


@pytest.mark.parametrize('name, call, expected', NO_BUTTON, ids=[case[0] for case in NO_BUTTON])
def test_events_without_button_have_no_keyboard(name, call, expected):
    assert _send(call).send_message.await_args.kwargs['reply_markup'] is None


def _button(bot: AsyncMock):
    markup = bot.send_message.await_args.kwargs['reply_markup']
    assert len(markup.inline_keyboard) == 1 and len(markup.inline_keyboard[0]) == 1
    return markup.inline_keyboard[0][0]


def test_button_events_keep_their_keyboards_with_miniapp(monkeypatch):
    monkeypatch.setattr(settings, 'MINIAPP_URL', 'https://mini.example')

    winback = _button(_send(lambda bot: ns.notify_winback(bot, telegram_id=CHAT)))
    abandoned = _button(_send(lambda bot: ns.notify_abandoned_payment(bot, telegram_id=CHAT)))
    nudge = _button(_send(lambda bot: ns.notify_welcome_nudge(bot, telegram_id=CHAT)))

    assert winback.text == '💎 Возобновить подписку' and winback.web_app.url.startswith('https://mini.example/payment')
    assert abandoned.text == '🔁 Попробовать снова' and abandoned.web_app.url.startswith('https://mini.example/payment')
    assert nudge.text == '🚀 Открыть приложение' and nudge.web_app.url.startswith('https://mini.example')
    assert '/payment' not in nudge.web_app.url


def test_button_events_keep_their_keyboards_without_miniapp(monkeypatch):
    monkeypatch.setattr(settings, 'MINIAPP_URL', '')

    winback = _button(_send(lambda bot: ns.notify_winback(bot, telegram_id=CHAT)))
    abandoned = _button(_send(lambda bot: ns.notify_abandoned_payment(bot, telegram_id=CHAT)))
    nudge = _button(_send(lambda bot: ns.notify_welcome_nudge(bot, telegram_id=CHAT)))

    assert (winback.text, winback.callback_data) == ('💎 Возобновить подписку', CB_SUBSCRIPTION_RENEW)
    assert (abandoned.text, abandoned.callback_data) == ('🔁 Попробовать снова', CB_SUBSCRIPTION_RENEW)
    assert (nudge.text, nudge.callback_data) == ('🚀 Открыть меню', 'sub:buy')


def test_notify_never_raises_when_telegram_fails():
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError('telegram down')

    asyncio.run(ns.notify_subscription_expired(bot, telegram_id=CHAT))  # не должно бросать
