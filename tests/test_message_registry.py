"""Реестр событий: целостность и заводские тексты."""

from __future__ import annotations

import re

import pytest

from app.services.message_templates.registry import EVENTS, EVENTS_BY_KEY, UnknownEventError, get_event

EXPECTED_KEYS = [
    'payment_success', 'referral_bonus', 'referral_invite_bonus', 'subscription_expiring', 'subscription_expired',
    'trial_ending', 'trial_expired', 'subscription_revoked', 'gift_redeemed', 'gift_code_ready', 'balance_credited', 'balance_debited', 'autopay_activated',
    'autopay_charge_failed', 'autopay_stopped', 'winback', 'abandoned_payment', 'welcome_nudge',
]
PLACEHOLDER = re.compile(r'\{([a-z_]+)\}')


def test_eighteen_events_in_spec_order():
    assert [event.key for event in EVENTS] == EXPECTED_KEYS
    assert len(EVENTS_BY_KEY) == 18


@pytest.mark.parametrize('event', EVENTS, ids=[event.key for event in EVENTS])
def test_event_is_self_consistent(event):
    placeholders = set(PLACEHOLDER.findall(event.default_template))
    assert placeholders <= set(event.variable_names), 'в заводском тексте есть переменная, которой нет в списке'
    assert set(event.required_variables) <= set(event.variable_names)
    assert set(event.required_variables) <= placeholders, 'обязательная переменная отсутствует в заводском тексте'
    assert event.group and event.title and event.trigger
    assert all(v.description and v.example for v in event.variables)
    rendered = event.default_template
    for name, example in event.samples().items():
        rendered = rendered.replace('{' + name + '}', example)
    assert '{' not in rendered and '}' not in rendered


def test_only_five_events_have_buttons():
    with_button = [event.key for event in EVENTS if event.has_button]

    assert with_button == ['trial_ending', 'trial_expired', 'winback', 'abandoned_payment', 'welcome_nudge']


def test_welcome_nudge_button_depends_on_miniapp():
    nudge = get_event('welcome_nudge')

    assert nudge.button_label(True) == '🚀 Открыть приложение'
    assert nudge.button_label(False) == '🚀 Открыть меню'
    assert get_event('winback').button_label(True) == get_event('winback').button_label(False) == '💎 Возобновить подписку'
    assert get_event('subscription_expired').button_label(True) is None


def test_gift_code_requires_link():
    assert get_event('gift_code_ready').required_variables == ('link',)


def test_unknown_event():
    with pytest.raises(UnknownEventError):
        get_event('no_such_event')


def test_default_texts_match_legacy_strings():
    assert get_event('payment_success').default_template == '✅ Оплата на сумму {amount}₽ прошла успешно. {description}'
    assert get_event('balance_debited').default_template == '💸 Средства списаны с баланса\n\nСумма: -{amount}₽\nТекущий баланс: {balance}₽'
    assert get_event('autopay_activated').default_template == '🔄 Автоплатёж подключён — подписка будет продлеваться автоматически каждый месяц.'
