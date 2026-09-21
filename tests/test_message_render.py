"""Подстановка переменных: экранирование и однопроходность."""

from __future__ import annotations

from app.services.message_templates.render import find_placeholders, render_template


def test_substitutes_placeholders():
    assert render_template('Сумма {amount}₽, баланс {balance}₽', {'amount': '100.00', 'balance': 350}) == 'Сумма 100.00₽, баланс 350₽'


def test_values_are_html_escaped_but_template_markup_is_kept():
    result = render_template('<b>Привет, {who}</b>', {'who': '<script>&"x"'})

    assert result == '<b>Привет, &lt;script&gt;&amp;&quot;x&quot;</b>'


def test_quote_in_value_is_escaped_inside_attribute():
    result = render_template('<a href="https://x/?u={who}">ссылка</a>', {'who': 'a"b'})

    assert result == '<a href="https://x/?u=a&quot;b">ссылка</a>'


def test_unknown_placeholder_is_left_untouched():
    assert render_template('Здравствуйте, {name}!', {'amount': '1'}) == 'Здравствуйте, {name}!'


def test_repeated_placeholder_and_no_recursive_substitution():
    assert render_template('{a} и {a}', {'a': '{b}', 'b': 'X'}) == '{b} и {b}'


def test_find_placeholders_unique_in_order():
    assert find_placeholders('{b} {a} {b} {c_d}') == ['b', 'a', 'c_d']
    assert find_placeholders('без переменных') == []
    assert find_placeholders('{Bad} {1x} { a }') == []  # только a-z и _
