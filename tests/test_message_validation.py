"""Проверки шаблона и подписи кнопки."""

from __future__ import annotations

import pytest

from app.services.message_templates.registry import EVENTS, get_event
from app.services.message_templates.validation import (
    MAX_BUTTON_LENGTH,
    MAX_TEXT_LENGTH,
    validate_button_text,
    validate_template,
)

PAYMENT = get_event('payment_success')  # переменные amount, description
GIFT = get_event('gift_code_ready')  # обязательная link
EXPIRED = get_event('subscription_expired')  # без переменных


@pytest.mark.parametrize('event', EVENTS, ids=[event.key for event in EVENTS])
def test_every_default_template_is_valid(event):
    result = validate_template(event, event.default_template)

    assert result.ok, result.errors
    assert result.warnings == []


def _errors(event, template) -> list[str]:
    return validate_template(event, template).errors


def test_allowed_formatting_and_links_pass():
    template = '<b>Жирный</b> <i>курсив</i> <u>под</u> <s>зач</s> <code>код</code> <a href="https://example.com/x?a=1">ссылка</a> <tg-spoiler>секрет</tg-spoiler> <blockquote expandable>цитата</blockquote> {amount}'

    assert validate_template(PAYMENT, template).ok


@pytest.mark.parametrize(
    'template',
    ['<script>alert(1)</script>', 'первая<br>строка', '<img src="x">', '<span>x</span>', '<h1>x</h1>'],
)
def test_unsupported_tags_are_rejected(template):
    assert any('не поддерживается' in error for error in _errors(EXPIRED, template))


def test_unbalanced_and_misnested_tags_are_rejected():
    assert _errors(EXPIRED, '<b>не закрыт')
    assert _errors(EXPIRED, 'лишний закрывающий</b>')
    assert _errors(EXPIRED, '<b><i>перепутаны</b></i>')


@pytest.mark.parametrize('href', ['javascript:alert(1)', 'ftp://x.y', '/relative', ''])
def test_dangerous_or_invalid_links_are_rejected(href):
    assert _errors(EXPIRED, f'<a href="{href}">x</a>')


def test_link_without_href_and_extra_attributes_are_rejected():
    assert _errors(EXPIRED, '<a>без ссылки</a>')
    assert _errors(EXPIRED, '<b class="x">лишний атрибут</b>')
    assert _errors(EXPIRED, '<a href="https://x.y" onclick="z">x</a>')


def test_tg_emoji_needs_numeric_id_and_produces_warning():
    good = validate_template(EXPIRED, '<tg-emoji emoji-id="5368446439800197476">🏦</tg-emoji> Подписка истекла')
    bad = validate_template(EXPIRED, '<tg-emoji emoji-id="abc">🏦</tg-emoji> текст')
    missing = validate_template(EXPIRED, '<tg-emoji>🏦</tg-emoji> текст')

    assert good.ok and any('Тест' in warning for warning in good.warnings)
    assert bad.errors and missing.errors


def test_unknown_variable_is_reported_with_available_ones():
    errors = _errors(PAYMENT, 'Привет {name}')

    assert any('{name}' in error and '{amount}' in error for error in errors)
    assert any('нет переменных' in error for error in _errors(EXPIRED, 'Привет {name}'))


def test_required_variable_must_be_present():
    errors = _errors(GIFT, 'Код создан, но ссылки нет')

    assert any('{link}' in error and 'обязательн' in error for error in errors)
    assert validate_template(GIFT, 'Держите: {link}').ok


@pytest.mark.parametrize('template', ['фигурная { скобка', 'закрывающая } скобка', '{ amount }', '{Amount}'])
def test_stray_braces_are_rejected(template):
    assert any('скобк' in error for error in _errors(PAYMENT, template))


def test_empty_text_is_rejected():
    assert _errors(EXPIRED, '')
    assert _errors(EXPIRED, '   \n ')
    assert _errors(EXPIRED, '<b></b>')


def test_raw_angle_bracket_in_text_is_rejected():
    assert any('&lt;' in error for error in _errors(EXPIRED, 'если a < b то плохо'))


def test_length_is_counted_on_visible_text_not_markup():
    assert validate_template(EXPIRED, '<b>' + 'а' * MAX_TEXT_LENGTH + '</b>').ok
    too_long = validate_template(EXPIRED, 'а' * (MAX_TEXT_LENGTH + 1))

    assert any('длин' in error for error in too_long.errors)
    assert validate_template(EXPIRED, 'а' * 10).visible_length == 10


def test_length_uses_example_values_of_variables():
    result = validate_template(PAYMENT, '{amount}{description}')

    assert result.visible_length == len('249.00') + len('Подписка «Онлайн» на 30 дн.')


def test_button_text_rules():
    winback = get_event('winback')

    assert validate_button_text(winback, '💎 Вернуться') == []
    assert validate_button_text(winback, '')
    assert validate_button_text(winback, 'x' * (MAX_BUTTON_LENGTH + 1))
    assert validate_button_text(winback, '<b>жирная</b>')
    assert validate_button_text(winback, '<tg-emoji emoji-id="1">x</tg-emoji>')
    assert validate_button_text(winback, 'с {переменной}')
    assert validate_button_text(EXPIRED, 'кнопка')  # у события нет кнопки
