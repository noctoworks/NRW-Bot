# Шаблоны сообщений бота — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать владельцу редактировать из веб-админки и из бота тексты 15 автоматических сообщений бота (включая кастомные эмодзи и форматирование), включать и выключать их, не теряя уведомлений при ошибках в шаблонах.

**Architecture:** Реестр событий с заводскими текстами живёт в коде; таблица `message_templates` хранит только правки. Все `notify_*` отправляют через `send_templated`: кэш правок, подстановка переменных с HTML-экранированием, откат на заводской текст при отказе Telegram. Одни и те же проверки шаблона используют API и редактор в боте.

**Tech Stack:** Python 3.12 (dev-машина 3.14), aiogram 3, FastAPI, SQLAlchemy 2 async, Alembic, pytest (без pytest-asyncio: `asyncio.run`), SQLite в тестах / Postgres в проде.

**Spec:** `docs/superpowers/specs/2026-09-21-message-templates-design.md` — прочитайте её целиком до начала.

## Прочитайте это первым (контекст для исполнителя)

**Проект.** `NRW-Bot` — Telegram-бот продажи VPN-подписок (Remnawave) + FastAPI-кабинет для Mini App и админки. Фронтенд — соседний репозиторий `../NRW-MiniApp`, **не трогайте его**: страница «Уведомления» пишется отдельно по контракту из `docs/api/`.

**Как устроены тесты (отличается от типичного).**
- Запуск: `python -m pytest tests -q -p no:warnings` (сейчас 199 тестов, все проходят; перед каждым коммитом весь набор обязан проходить).
- Нет `pytest-asyncio`: каждый тест — обычная функция, внутри `asyncio.run(scenario())` с `async def scenario()`.
- Фикстура `session_factory` (в `tests/conftest.py`) — файловая SQLite во временной папке; `make_user`, `make_tariff` — в `tests/helpers.py`.
- Бот в тестах — `AsyncMock()`; сообщения проверяются по `bot.send_message.await_args.kwargs`.
- SQLite возвращает naive-даты, Postgres — aware.

**Ловушки окружения (Windows).**
- Длинные `python - <<'EOF'` в Bash-инструменте ломаются: создавайте файлы инструментом Write, скрипты запускайте отдельно.
- PowerShell 5.1: `Set-Content -Encoding UTF8` пишет BOM — не используйте для кода.
- Часть файлов имеет CRLF: однострочные правки через Edit безопасны, для многострочных замен используйте помощник из Приложения A.
- `set PYTHONIOENCODING=utf-8` для вывода кириллицы.

**Коммиты.** Сообщения на русском (стиль репозитория), в конце — атрибуция, которую требует ваша среда. Не пушить. Один коммит на задачу.

**Контекст про Telegram.** Бот создаётся с `parse_mode=HTML` (`app/bot.py`), поэтому все тексты — HTML Telegram. Кастомные эмодзи в тексте — тег `<tg-emoji emoji-id="…">символ</tg-emoji>`; fallback-символ обязан совпадать с «родным» символом эмодзи, иначе Telegram отклоняет сообщение. В тексте inline-кнопок кастомные эмодзи запрещены. Отправлять кастомные эмодзи от имени бота может только бот, чей владелец имеет Telegram Premium (см. `app/emoji.py`).

## Global Constraints

Значения из спецификации, дословно.

- Языки: **только русский**, колонки языка нет.
- Объём: **15 событий** — `payment_success`, `referral_bonus`, `referral_invite_bonus`, `subscription_expiring`, `subscription_expired`, `gift_redeemed`, `gift_code_ready`, `balance_credited`, `balance_debited`, `autopay_activated`, `autopay_charge_failed`, `autopay_stopped`, `winback`, `abandoned_payment`, `welcome_nudge`.
- Заводские тексты — **дословно текущие**; без правок поведение бота не меняется ни на символ.
- Разметка — HTML Telegram; подстановки `{имя}` только из разрешённого списка события; значения переменных экранируются как HTML.
- Разрешённые теги: `b`, `strong`, `i`, `em`, `u`, `ins`, `s`, `strike`, `del`, `a` (только `href` со схемами `https`/`http`/`tg`), `code`, `pre`, `tg-spoiler`, `blockquote`, `tg-emoji` (только `emoji-id` из цифр); теги парные и вложены правильно.
- Лимит: видимый текст ≤ 4096 символов. Подпись кнопки: 1–64 символа, без разметки и без кастомных эмодзи.
- Кэш правок: перезагрузка не реже 60 секунд и немедленный сброс после сохранения/сброса. Сбой чтения БД → заводские тексты.
- `notify_*` **никогда не бросают исключение**; сигнатуры сохраняются; отправка идёт вызовом `bot.send_message(chat_id=…, text=…, reply_markup=…)`.
- Отказ Telegram из-за разметки/эмодзи → автоматическая отправка заводского текста (ровно одна повторная отправка) + лог `template_fallback`.
- Таблица `message_templates`: PK `key`; миграция только добавляющая; сохранение и сброс пишутся в лог (`template_updated`, `template_reset`) без самого текста.
- API: `/cabinet/admin/notifications/*`, `require_admin`; ошибки проверок — `422` в формате FastAPI (`detail: [{loc, msg, type}]`).
- Бот: `/admin` → «✉️ Сообщения», только `is_admin`; текст берётся из `message.html_text`.
- Комментарии и docstring — на русском, в стиле окружающего кода.

## Решения, принятые планом (уточнения к спецификации)

1. `message_templates.template` — **nullable**: `NULL` = «использовать заводской текст». Так можно выключить событие или сменить подпись кнопки, не трогая текст. `is_customized` = `template is not None`. «Сбросить» удаляет строку целиком (текст, кнопка, флаг). Спецификация обновляется в Task 4.
2. Заводская подпись кнопки у `welcome_nudge` зависит от `MINIAPP_URL` («🚀 Открыть приложение» / «🚀 Открыть меню»); правка подписи заменяет обе.
3. Откат на заводской текст включается только при ошибках разметки/эмодзи/длины (сообщение `TelegramBadRequest` содержит `parse entities`, `entity`, `emoji`, `too long` или `text is empty`); остальные `TelegramBadRequest` (например, `chat not found`) только логируются.
4. Обработчики редактора в боте выделены в отдельный модуль `app/handlers/message_templates_admin.py` (префикс callback — `tpl:`), чтобы не раздувать `handlers/admin.py`.
5. Тестовое сообщение («Тест мне») отправляется с настоящей клавиатурой события (если она есть) и с примерами переменных из реестра.

## Карта файлов

| Файл | Действие | Ответственность |
|---|---|---|
| `tests/test_notifications_golden.py` | создать | характеризационные тесты текущих `notify_*` (проходят до и после рефакторинга) |
| `app/services/message_templates/__init__.py` | создать | пустой пакет |
| `app/services/message_templates/registry.py` | создать | 15 событий, заводские тексты, переменные |
| `app/services/message_templates/render.py` | создать | подстановка переменных с экранированием |
| `app/services/message_templates/validation.py` | создать | проверки шаблона и подписи кнопки |
| `app/database/models.py` | изменить | модель `MessageTemplate` |
| `migrations/versions/<rev>_add_message_templates.py` | создать | миграция |
| `app/services/message_templates/service.py` | создать | кэш, сохранение/сброс, `send_templated`, тестовая отправка |
| `app/services/notification_service.py` | изменить | `notify_*` → тонкие обёртки над `send_templated` |
| `app/cabinet/notifications_schemas.py`, `notifications_routes.py` | создать | API |
| `app/cabinet/app.py` | изменить | подключить роутер |
| `app/states.py`, `app/handlers/message_templates_admin.py`, `app/handlers/__init__.py`, `app/handlers/admin.py` | изменить/создать | редактор в боте |
| `scripts/generate_api_docs.py`, `docs/api/*` | изменить/перегенерировать | документация API |
| `docs/superpowers/specs/2026-09-21-message-templates-design.md` | изменить | уточнение схемы (`template` nullable) |

## Приложение A. Помощник для многострочных правок

Создайте `apply_patch.py` во временной папке (не в репозитории). Заменяет ровно одно вхождение, падает при 0 или более 1; сохраняет CRLF/LF файла.

```python
def apply_patch(path: str, old: str, new: str) -> None:
    text = open(path, encoding='utf-8', newline='').read()
    crlf = '\r\n' in text
    text = text.replace('\r\n', '\n')
    count = text.count(old)
    assert count == 1, f'{path}: фрагмент найден {count} раз(а), нужен ровно 1:\n{old[:120]}'
    text = text.replace(old, new, 1)
    if crlf:
        text = text.replace('\n', '\r\n')
    open(path, 'w', encoding='utf-8', newline='').write(text)
```

---

### Task 1: Характеризационные тесты текущих уведомлений

Цель — зафиксировать поведение **до** рефакторинга: эти тесты должны проходить на текущем коде и продолжить проходить после Task 6. Они гарантируют «ни символа не изменилось».

**Files:**
- Create: `tests/test_notifications_golden.py`

**Interfaces:**
- Consumes: существующие `notify_*` из `app/services/notification_service.py` (сигнатуры не меняются), `settings.MINIAPP_URL`, `CB_SUBSCRIPTION_RENEW` из `app/keyboards/main_menu.py`.
- Produces: тесты `test_text_is_unchanged`, `test_button_events_keep_their_keyboards`, `test_send_call_shape`.

- [ ] **Step 1: Написать тесты**

Создайте `tests/test_notifications_golden.py`:

```python
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
```

- [ ] **Step 2: Запустить на ТЕКУЩЕМ коде — должно пройти**

Run: `python -m pytest tests/test_notifications_golden.py -q -p no:warnings`
Expected: все PASS (это характеризация существующего поведения). Если что-то падает — тест расходится с кодом: исправьте **тест** по `app/services/notification_service.py` (код в этой задаче не меняем).

- [ ] **Step 3: Весь набор и коммит**

Run: `python -m pytest tests -q -p no:warnings` → PASS.

```bash
git add tests/test_notifications_golden.py
git commit -m "Добавляет характеризационные тесты автоматических уведомлений"
```

---

### Task 2: Реестр событий

**Files:**
- Create: `app/services/message_templates/__init__.py` (пустой), `app/services/message_templates/registry.py`
- Test: `tests/test_message_registry.py`

**Interfaces:**
- Produces:
  - `UnknownEventError(KeyError)`
  - `Variable(name: str, description: str, example: str)` (frozen dataclass)
  - `EventDef` (frozen dataclass): `key, group, title, trigger, default_template, variables: tuple[Variable, ...] = (), required_variables: tuple[str, ...] = (), default_button_text: str | None = None, default_button_text_no_miniapp: str | None = None`; свойства `variable_names -> tuple[str, ...]`, `has_button -> bool`; метод `samples() -> dict[str, str]`; метод `button_label(miniapp_enabled: bool) -> str | None`.
  - `EVENTS: tuple[EventDef, ...]` (15 событий в порядке из спецификации), `EVENTS_BY_KEY: dict[str, EventDef]`, `get_event(key: str) -> EventDef` (неизвестный ключ → `UnknownEventError`).

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_message_registry.py`:

```python
"""Реестр событий: целостность и заводские тексты."""

from __future__ import annotations

import re

import pytest

from app.services.message_templates.registry import EVENTS, EVENTS_BY_KEY, UnknownEventError, get_event

EXPECTED_KEYS = [
    'payment_success', 'referral_bonus', 'referral_invite_bonus', 'subscription_expiring', 'subscription_expired',
    'gift_redeemed', 'gift_code_ready', 'balance_credited', 'balance_debited', 'autopay_activated',
    'autopay_charge_failed', 'autopay_stopped', 'winback', 'abandoned_payment', 'welcome_nudge',
]
PLACEHOLDER = re.compile(r'\{([a-z_]+)\}')


def test_fifteen_events_in_spec_order():
    assert [event.key for event in EVENTS] == EXPECTED_KEYS
    assert len(EVENTS_BY_KEY) == 15


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


def test_only_three_events_have_buttons():
    with_button = [event.key for event in EVENTS if event.has_button]

    assert with_button == ['winback', 'abandoned_payment', 'welcome_nudge']


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
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_message_registry.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError: app.services.message_templates`).

- [ ] **Step 3: Реализация**

Создайте пустой `app/services/message_templates/__init__.py` и `app/services/message_templates/registry.py`:

```python
"""Реестр автоматических сообщений бота: события, заводские тексты, переменные.

Заводские тексты — ДОСЛОВНО те, что раньше были зашиты в notification_service.py; они же служат
запасным вариантом, если правки владельца не заданы, выключены или отклонены Telegram.
Правки хранятся в таблице message_templates (см. service.py)."""

from __future__ import annotations

from dataclasses import dataclass


class UnknownEventError(KeyError):
    """Ключа события нет в реестре."""


@dataclass(frozen=True)
class Variable:
    name: str
    description: str
    example: str


@dataclass(frozen=True)
class EventDef:
    key: str
    group: str
    title: str
    trigger: str
    default_template: str
    variables: tuple[Variable, ...] = ()
    required_variables: tuple[str, ...] = ()
    default_button_text: str | None = None
    # Только у welcome_nudge: без MINIAPP_URL кнопка называется иначе (запасной callback).
    default_button_text_no_miniapp: str | None = None

    @property
    def variable_names(self) -> tuple[str, ...]:
        return tuple(variable.name for variable in self.variables)

    @property
    def has_button(self) -> bool:
        return self.default_button_text is not None

    def samples(self) -> dict[str, str]:
        return {variable.name: variable.example for variable in self.variables}

    def button_label(self, miniapp_enabled: bool) -> str | None:
        if self.default_button_text is None:
            return None
        if not miniapp_enabled and self.default_button_text_no_miniapp is not None:
            return self.default_button_text_no_miniapp
        return self.default_button_text


_AMOUNT = Variable('amount', 'Сумма в рублях числом, без знака ₽ (например 249.00)', '249.00')

EVENTS: tuple[EventDef, ...] = (
    EventDef(
        key='payment_success',
        group='Платежи',
        title='Оплата прошла',
        trigger='Платёж подтверждён: покупка, продление подписки или автоплатёж',
        default_template='✅ Оплата на сумму {amount}₽ прошла успешно. {description}',
        variables=(_AMOUNT, Variable('description', 'Что оплачено (например «Подписка «Онлайн» на 30 дн.»)', 'Подписка «Онлайн» на 30 дн.')),
    ),
    EventDef(
        key='referral_bonus',
        group='Рефералы',
        title='Реферальное начисление',
        trigger='Приглашённый вами пользователь оплатил — вам начислена комиссия',
        default_template='🎉 Вам начислено {amount}₽ реферальных бонусов!',
        variables=(Variable('amount', 'Сумма комиссии в рублях числом, без знака ₽', '25.00'),),
    ),
    EventDef(
        key='referral_invite_bonus',
        group='Рефералы',
        title='Бонус за приглашённого друга',
        trigger='Друг зарегистрировался по вашей ссылке — вам начислены дни подписки',
        default_template=(
            '🚀 По вашей ссылке зарегистрировался друг — начислено +{bonus_days} дн. подписки!\n\n'
            'Приглашайте ещё — бонус начисляется за каждого нового друга.'
        ),
        variables=(Variable('bonus_days', 'Сколько дней подписки начислено', '3'),),
    ),
    EventDef(
        key='subscription_expiring',
        group='Подписка',
        title='Подписка скоро истечёт',
        trigger='За 3 дня и за 1 день до окончания подписки',
        default_template='⏳ Ваша подписка истекает через {days_left} дн.',
        variables=(Variable('days_left', 'Сколько дней осталось (3 или 1)', '3'),),
    ),
    EventDef(
        key='subscription_expired',
        group='Подписка',
        title='Подписка истекла',
        trigger='Подписка закончилась',
        default_template='❌ Ваша подписка истекла. Продлите её в главном меню.',
    ),
    EventDef(
        key='gift_redeemed',
        group='Подарки',
        title='Подарок активирован',
        trigger='Получатель активировал подарочный код (сообщение дарителю)',
        default_template='🎁 Ваш подарок активировал {who}!',
        variables=(Variable('who', '@username получателя или слово «пользователь»', '@friend'),),
    ),
    EventDef(
        key='gift_code_ready',
        group='Подарки',
        title='Подарочный код создан',
        trigger='Платёж за подарок подтверждён асинхронно — код создан',
        default_template=(
            '🎉 Оплата прошла успешно! Подарочный код создан.\n\n'
            'Отправьте эту ссылку тому, кому хотите подарить подписку:\n{link}\n\n'
            'Код действителен 30 дней.'
        ),
        variables=(Variable('link', 'Ссылка на подарок (обязательна: без неё код нельзя передать)', 'https://t.me/nrw_bot?start=gift_ABC123'),),
        required_variables=('link',),
    ),
    EventDef(
        key='balance_credited',
        group='Баланс',
        title='Баланс пополнен',
        trigger='Администратор начислил средства на баланс',
        default_template='💰 Баланс пополнен!\n\nСумма: +{amount}₽\nТекущий баланс: {balance}₽',
        variables=(
            Variable('amount', 'Начисленная сумма в рублях числом, без знака ₽', '100.00'),
            Variable('balance', 'Баланс после начисления в рублях числом', '350.00'),
        ),
    ),
    EventDef(
        key='balance_debited',
        group='Баланс',
        title='Средства списаны с баланса',
        trigger='Администратор списал средства с баланса',
        default_template='💸 Средства списаны с баланса\n\nСумма: -{amount}₽\nТекущий баланс: {balance}₽',
        variables=(
            Variable('amount', 'Списанная сумма в рублях числом (без знака)', '50.00'),
            Variable('balance', 'Баланс после списания в рублях числом', '300.00'),
        ),
    ),
    EventDef(
        key='autopay_activated',
        group='Автоплатёж',
        title='Автоплатёж подключён',
        trigger='Платёжная система подтвердила подключение автоплатежа',
        default_template='🔄 Автоплатёж подключён — подписка будет продлеваться автоматически каждый месяц.',
    ),
    EventDef(
        key='autopay_charge_failed',
        group='Автоплатёж',
        title='Не удалось списать автоплатёж',
        trigger='Очередное автосписание не прошло',
        default_template=(
            '⚠️ Не удалось списать автоплатёж — проверьте, что на карте/счёте достаточно средств.\n\n'
            'Подписка продолжает действовать до текущей даты окончания.'
        ),
    ),
    EventDef(
        key='autopay_stopped',
        group='Автоплатёж',
        title='Автоплатёж отключён',
        trigger='Банк отклонил привязку или списания подряд не проходят',
        default_template=(
            '🔕 Автоплатёж отключён (банк отклонил привязку или списания подряд не проходят).\n\n'
            'Подписку можно продлить вручную в любой момент.'
        ),
    ),
    EventDef(
        key='winback',
        group='Возврат клиентов',
        title='Возвращение клиента',
        trigger='Через 7 дней после истечения подписки, если её не продлили',
        default_template=(
            '👋 Соскучились? Ваша подписка уже некоторое время неактивна — '
            'самое время вернуться, пока для вас держим ваш профиль и настройки.'
        ),
        default_button_text='💎 Возобновить подписку',
    ),
    EventDef(
        key='abandoned_payment',
        group='Возврат клиентов',
        title='Оплата не завершена',
        trigger='Через 1 час после создания платежа, который так и не оплачен',
        default_template=(
            '💳 Похоже, оплата не завершилась. Если передумали или что-то пошло не '
            'так — можно оформить заново, это займёт минуту.'
        ),
        default_button_text='🔁 Попробовать снова',
    ),
    EventDef(
        key='welcome_nudge',
        group='Возврат клиентов',
        title='Напоминание после регистрации',
        trigger='Через 24 часа после регистрации, если пользователь ничего не купил',
        default_template=(
            '🔐 Не забыли про VPN? Пробный период уже начался — попробуйте подключиться '
            'сейчас, а когда пробный период закончится, сможете оформить подписку в один тап.'
        ),
        default_button_text='🚀 Открыть приложение',
        default_button_text_no_miniapp='🚀 Открыть меню',
    ),
)

EVENTS_BY_KEY: dict[str, EventDef] = {event.key: event for event in EVENTS}


def get_event(key: str) -> EventDef:
    try:
        return EVENTS_BY_KEY[key]
    except KeyError:
        raise UnknownEventError(key) from None
```

- [ ] **Step 4: Тесты проходят**

Run: `python -m pytest tests/test_message_registry.py tests/test_notifications_golden.py -q -p no:warnings` → PASS; затем весь набор.

- [ ] **Step 5: Сверка заводских текстов с кодом**

Заводские тексты реестра должны равняться текущим в `notification_service.py`. Окончательно это гарантирует Task 6 (характеризационные тесты пройдут на шаблонах); сейчас просто сверьте глазами каждый `default_template` с соответствующей функцией.

- [ ] **Step 6: Коммит**

```bash
git add app/services/message_templates tests/test_message_registry.py
git commit -m "Добавляет реестр автоматических сообщений с заводскими текстами"
```

### Task 3: Подстановка переменных и проверки шаблона

**Files:**
- Create: `app/services/message_templates/render.py`, `app/services/message_templates/validation.py`
- Test: `tests/test_message_render.py`, `tests/test_message_validation.py`

**Interfaces:**
- Consumes: `EventDef`, `EVENTS` из `registry.py` (Task 2).
- Produces:
  - `render.PLACEHOLDER_RE` (`re.Pattern`, `\{([a-z_]+)\}`), `render.find_placeholders(template: str) -> list[str]` (уникальные, в порядке появления), `render.render_template(template: str, variables: Mapping[str, object]) -> str` — подставляет `{имя}`, значения экранируются HTML (`html.escape(str(v), quote=False)`), неизвестные имена остаются как есть, подстановка однопроходная (значение не подставляется повторно).
  - `validation.ValidationResult` (dataclass): `errors: list[str]`, `warnings: list[str]`, `visible_length: int`, свойство `ok -> bool`.
  - `validation.validate_template(event: EventDef, template: str) -> ValidationResult`
  - `validation.validate_button_text(event: EventDef, text: str) -> list[str]` (список ошибок; пустой = верно)
  - Константы `ALLOWED_TAGS`, `MAX_TEXT_LENGTH = 4096`, `MAX_BUTTON_LENGTH = 64`.

- [ ] **Step 1: Падающие тесты на подстановку**

Создайте `tests/test_message_render.py`:

```python
"""Подстановка переменных: экранирование и однопроходность."""

from __future__ import annotations

from app.services.message_templates.render import find_placeholders, render_template


def test_substitutes_placeholders():
    assert render_template('Сумма {amount}₽, баланс {balance}₽', {'amount': '100.00', 'balance': 350}) == 'Сумма 100.00₽, баланс 350₽'


def test_values_are_html_escaped_but_template_markup_is_kept():
    result = render_template('<b>Привет, {who}</b>', {'who': '<script>&"x"'})

    assert result == '<b>Привет, &lt;script&gt;&amp;"x"</b>'


def test_unknown_placeholder_is_left_untouched():
    assert render_template('Здравствуйте, {name}!', {'amount': '1'}) == 'Здравствуйте, {name}!'


def test_repeated_placeholder_and_no_recursive_substitution():
    assert render_template('{a} и {a}', {'a': '{b}', 'b': 'X'}) == '{b} и {b}'


def test_find_placeholders_unique_in_order():
    assert find_placeholders('{b} {a} {b} {c_d}') == ['b', 'a', 'c_d']
    assert find_placeholders('без переменных') == []
    assert find_placeholders('{Bad} {1x} { a }') == []  # только a-z и _
```

- [ ] **Step 2: Падающие тесты на проверки**

Создайте `tests/test_message_validation.py`:

```python
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
```

- [ ] **Step 3: Убедиться, что падают**

Run: `python -m pytest tests/test_message_render.py tests/test_message_validation.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Реализация подстановки**

Создайте `app/services/message_templates/render.py`:

```python
"""Подстановка переменных {имя} в шаблон сообщения.

Значения экранируются как HTML (бот шлёт сообщения с parse_mode=HTML): имя пользователя с `<`
или `&` не должно ломать разметку. Сам шаблон — доверенная разметка владельца (её проверяет
validation.py при сохранении)."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping

PLACEHOLDER_RE = re.compile(r'\{([a-z_]+)\}')


def find_placeholders(template: str) -> list[str]:
    """Имена переменных в порядке появления, без повторов."""
    return list(dict.fromkeys(PLACEHOLDER_RE.findall(template)))


def render_template(template: str, variables: Mapping[str, object]) -> str:
    """Однопроходная подстановка: подставленное значение повторно не разбирается.
    Неизвестные имена остаются как есть (валидный шаблон их не содержит)."""

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in variables:
            return match.group(0)
        return html.escape(str(variables[name]), quote=False)

    return PLACEHOLDER_RE.sub(replace, template)
```

- [ ] **Step 5: Реализация проверок**

Создайте `app/services/message_templates/validation.py`:

```python
"""Проверки шаблона сообщения при сохранении (одни и те же для API и редактора в боте)."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

from app.services.message_templates.registry import EventDef
from app.services.message_templates.render import PLACEHOLDER_RE, find_placeholders, render_template

# Теги, которые поддерживает HTML-режим Telegram (https://core.telegram.org/bots/api#html-style).
ALLOWED_TAGS = frozenset(
    {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'a', 'code', 'pre', 'tg-spoiler', 'blockquote', 'tg-emoji'}
)
ALLOWED_LINK_PREFIXES = ('https://', 'http://', 'tg://')
MAX_TEXT_LENGTH = 4096  # лимит Telegram на длину видимого текста сообщения
MAX_BUTTON_LENGTH = 64


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    visible_length: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


class _MarkupChecker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.text: list[str] = []
        self.has_emoji = False

    def _error(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            self._error(f'Тег <{tag}> не поддерживается Telegram. Разрешены: {", ".join(sorted(ALLOWED_TAGS))}.')
            return
        attributes = dict(attrs)
        if tag == 'a':
            href = (attributes.get('href') or '').strip()
            if not href.lower().startswith(ALLOWED_LINK_PREFIXES):
                self._error('У ссылки <a> нужен href, начинающийся с https://, http:// или tg://.')
            extra = set(attributes) - {'href'}
        elif tag == 'tg-emoji':
            self.has_emoji = True
            emoji_id = attributes.get('emoji-id') or ''
            if not emoji_id.isdigit():
                self._error('У <tg-emoji> нужен атрибут emoji-id из цифр (ID кастомного эмодзи).')
            extra = set(attributes) - {'emoji-id'}
        elif tag == 'blockquote':
            extra = set(attributes) - {'expandable'}
        else:
            extra = set(attributes)
        if extra:
            self._error(f'У тега <{tag}> не поддерживаются атрибуты: {", ".join(sorted(extra))}.')
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag not in ALLOWED_TAGS:
            self._error(f'Тег </{tag}> не поддерживается Telegram.')
        elif not self.stack or self.stack[-1] != tag:
            self._error(f'Лишний или неправильно вложенный закрывающий тег </{tag}>.')
        else:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def finish(self) -> None:
        self.close()
        if self.stack:
            self._error('Не закрыты теги: ' + ', '.join(f'<{tag}>' for tag in self.stack) + '.')


def validate_template(event: EventDef, template: str) -> ValidationResult:
    result = ValidationResult()

    # 1. Фигурные скобки допустимы только в виде известных переменных.
    if '{' in PLACEHOLDER_RE.sub('', template) or '}' in PLACEHOLDER_RE.sub('', template):
        result.errors.append('Фигурные скобки допустимы только для переменных вида {имя} (строчные латинские буквы и _).')

    # 2. Переменные события.
    used = find_placeholders(template)
    allowed = event.variable_names
    unknown = [name for name in used if name not in allowed]
    if unknown:
        listing = ', '.join('{' + name + '}' for name in allowed)
        for name in unknown:
            if allowed:
                result.errors.append('Неизвестная переменная {' + name + '}. Доступны: ' + listing + '.')
            else:
                result.errors.append('Неизвестная переменная {' + name + '}: в этом сообщении нет переменных.')
    for name in event.required_variables:
        if name not in used:
            result.errors.append('Переменная {' + name + '} обязательна и должна быть в тексте.')

    # 3. Разметка и длина — на тексте с примерами значений (значения экранируются, тегов не добавят).
    checker = _MarkupChecker()
    checker.feed(render_template(template, event.samples()))
    checker.finish()
    result.errors.extend(error for error in checker.errors if error not in result.errors)

    visible = ''.join(checker.text)
    result.visible_length = len(visible)
    if '<' in visible:
        result.errors.append('Символ < в обычном тексте нужно писать как &lt; (и > как &gt;).')
    if not visible.strip():
        result.errors.append('Текст не может быть пустым.')
    if result.visible_length > MAX_TEXT_LENGTH:
        result.errors.append(f'Слишком большая длина: {result.visible_length} символов, максимум {MAX_TEXT_LENGTH}.')

    if checker.has_emoji:
        result.warnings.append(
            'В тексте есть кастомные эмодзи: Telegram проверяет их только при отправке — нажмите «Тест». '
            'Если эмодзи окажется недопустимым, пользователь получит заводской текст.'
        )
    return result


def validate_button_text(event: EventDef, text: str) -> list[str]:
    if not event.has_button:
        return ['У этого сообщения нет кнопки.']
    errors: list[str] = []
    stripped = text.strip()
    if not stripped:
        errors.append('Подпись кнопки не может быть пустой.')
    if len(stripped) > MAX_BUTTON_LENGTH:
        errors.append(f'Подпись кнопки слишком длинная: {len(stripped)} символов, максимум {MAX_BUTTON_LENGTH}.')
    if any(char in stripped for char in '<>&{}'):
        errors.append('В подписи кнопки нельзя использовать разметку и переменные (в том числе кастомные эмодзи).')
    return errors
```

- [ ] **Step 6: Тесты проходят**

Run: `python -m pytest tests/test_message_render.py tests/test_message_validation.py -q -p no:warnings` → PASS; затем весь набор.
Если `test_length_is_counted_on_visible_text_not_markup` падает на границе — HTMLParser может дробить длинный `data` на куски; это учтено, так как `text` — список, склеиваемый перед подсчётом.

- [ ] **Step 7: Мутации**

По одной, каждая роняет тест, затем откат: убрать `quote=False` → `html.escape(..)` не должно ломаться, поэтому вместо этого уберите `html.escape` целиком (упадёт тест экранирования); убрать проверку `href` префикса (упадёт `test_dangerous_or_invalid_links…`); заменить `result.visible_length > MAX_TEXT_LENGTH` на `>=` (упадёт тест длины).

- [ ] **Step 8: Коммит**

```bash
git add app/services/message_templates/render.py app/services/message_templates/validation.py tests/test_message_render.py tests/test_message_validation.py
git commit -m "Добавляет подстановку переменных и проверки шаблонов сообщений"
```

---

### Task 4: Модель `MessageTemplate` и миграция

**Files:**
- Modify: `app/database/models.py`, `docs/superpowers/specs/2026-09-21-message-templates-design.md`
- Create: `migrations/versions/d4e8b1a7c305_add_message_templates.py`
- Test: `tests/test_message_templates_model.py`

**Interfaces:**
- Produces: ORM-модель `MessageTemplate` (`__tablename__ = 'message_templates'`): `key: str` (PK, `String(64)`), `template: str | None` (`Text`, nullable; `NULL` = заводской текст), `button_text: str | None` (`String(64)`), `enabled: bool` (default `True`, server default true), `updated_at: datetime` (server default now), `updated_by_user_id: int | None` (FK `users.id`, `ON DELETE SET NULL`).

- [ ] **Step 1: Определить текущую голову миграций**

Run (PowerShell): `$env:BOT_TOKEN='1:t'; python -m alembic heads`
Expected: одна голова. На момент написания плана — `caa7bbb89896`; если уже применён план аналитики — `b7d1e5a93c20`. Значение подставляется в `down_revision` ниже. Если голов больше одной — остановитесь и разберитесь (цепочка сломана).

- [ ] **Step 2: Падающие тесты**

Создайте `tests/test_message_templates_model.py`:

```python
"""Модель MessageTemplate и её миграция."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.database.models import Base, MessageTemplate, User
from tests.helpers import make_user

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = next((ROOT / 'migrations' / 'versions').glob('*_add_message_templates.py'))


def _load_migration():
    spec = importlib.util.spec_from_file_location('mig_message_templates', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(engine, table: str) -> dict:
    inspector = sa.inspect(engine)
    return {
        'columns': {c['name']: (str(c['type']).upper(), c['nullable']) for c in inspector.get_columns(table)},
        'indexes': {i['name']: (tuple(i['column_names']), bool(i['unique'])) for i in inspector.get_indexes(table)},
        'pk': inspector.get_pk_constraint(table)['constrained_columns'],
    }


def test_single_alembic_head():
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'migrations'))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1


def test_migration_result_matches_model():
    expected = sa.create_engine('sqlite://')
    Base.metadata.create_all(expected)
    actual = sa.create_engine('sqlite://')
    Base.metadata.create_all(actual, tables=[t for t in Base.metadata.sorted_tables if t.name != 'message_templates'])
    with actual.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration().upgrade()

    assert _schema(actual, 'message_templates') == _schema(expected, 'message_templates')
    foreign_keys = {fk['constrained_columns'][0]: fk['options'].get('ondelete') for fk in sa.inspect(actual).get_foreign_keys('message_templates')}
    assert foreign_keys == {'updated_by_user_id': 'SET NULL'}


def test_migration_downgrade_drops_the_table():
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration().downgrade()

    assert 'message_templates' not in sa.inspect(engine).get_table_names()


def test_model_defaults_and_nullable_template(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, is_admin=True)
        async with session_factory() as db:
            db.add(MessageTemplate(key='winback', updated_by_user_id=admin_id))  # только вкл/выкл и кнопка — текст не задан
            await db.commit()
        async with session_factory() as db:
            row = (await db.execute(select(MessageTemplate))).scalar_one()
            assert (row.key, row.template, row.button_text, row.enabled) == ('winback', None, None, True)
            assert row.updated_at is not None and row.updated_by_user_id == admin_id

    asyncio.run(scenario())


def test_deleting_the_admin_keeps_the_template(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory)
        async with session_factory() as db:
            db.add(MessageTemplate(key='winback', template='Привет', updated_by_user_id=admin_id))
            await db.commit()
        async with session_factory() as db:
            # SQLite-фикстура без PRAGMA foreign_keys: проверяем, что модель допускает NULL у автора
            row = await db.get(MessageTemplate, 'winback')
            row.updated_by_user_id = None
            await db.commit()
            assert (await db.get(MessageTemplate, 'winback')).template == 'Привет'

    asyncio.run(scenario())
```

- [ ] **Step 3: Убедиться, что падает**

Run: `python -m pytest tests/test_message_templates_model.py -q -p no:warnings`
Expected: FAIL (`StopIteration`: файл миграции не найден / `ImportError: MessageTemplate`).

- [ ] **Step 4: Модель**

В `app/database/models.py` (в конец файла; `Boolean`, `DateTime`, `ForeignKey`, `String`, `Text`, `func` уже импортированы — проверьте, при необходимости добавьте `Text` и `true` в строку `from sqlalchemy import …`):

```python
class MessageTemplate(Base):
    """Правки владельца к автоматическим сообщениям бота. Строки создаются только при правке;
    заводские тексты живут в коде (app/services/message_templates/registry.py). template = NULL —
    «использовать заводской текст» (строка нужна, чтобы выключить событие или сменить подпись кнопки)."""

    __tablename__ = 'message_templates'

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    template: Mapped[str | None] = mapped_column(Text, nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
```

- [ ] **Step 5: Миграция**

Создайте `migrations/versions/d4e8b1a7c305_add_message_templates.py`, подставив `down_revision` из Step 1:

```python
"""add message_templates

Revision ID: d4e8b1a7c305
Revises: caa7bbb89896
Create Date: 2026-09-21 18:00:00.000000

Только добавляющая миграция (новая таблица) — откат безопасен. Пустая таблица = бот шлёт заводские тексты.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e8b1a7c305'
down_revision = 'caa7bbb89896'  # ← подставьте результат `alembic heads` (Step 1)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'message_templates',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('template', sa.Text(), nullable=True),
        sa.Column('button_text', sa.String(length=64), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('message_templates')
```

Если в репозитории уже есть `tests/test_migrations.py` (из плана аналитики) с проверкой `get_heads() == ['b7d1e5a93c20']`, замените её на «одна голова, и она наследует эту миграцию»:

```python
def test_alembic_has_single_head_after_new_migration():
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    script = ScriptDirectory.from_config(config)

    assert len(script.get_heads()) == 1
    assert 'b7d1e5a93c20' in {revision.revision for revision in script.walk_revisions()}
```

- [ ] **Step 6: Уточнить спецификацию**

В `docs/superpowers/specs/2026-09-21-message-templates-design.md`, раздел 5, замените строку таблицы `| \`template\` | text | текст в HTML Telegram |` на `| \`template\` | text, nullable | текст в HTML Telegram; NULL — использовать заводской текст (строка нужна, чтобы выключить событие или сменить подпись кнопки) |`, а фразу «Строки создаются только при правке; «Сбросить» удаляет строку» дополните: «(и текст, и кнопку, и флаг)».

- [ ] **Step 7: Тесты, проверка SQL и коммит**

Run: `python -m pytest tests -q -p no:warnings` → PASS.
Run (PowerShell): `$env:BOT_TOKEN='1:t'; $env:DATABASE_URL='postgresql+asyncpg://u:p@h/db'; python -m alembic upgrade caa7bbb89896:d4e8b1a7c305 --sql` (если голова была другой — подставьте её вместо `caa7bbb89896`)
Expected: `CREATE TABLE message_templates` и `UPDATE alembic_version`, без ошибок.

```bash
git add app/database/models.py migrations/versions/d4e8b1a7c305_add_message_templates.py tests/test_message_templates_model.py docs/superpowers/specs/2026-09-21-message-templates-design.md
git commit -m "Добавляет таблицу message_templates для правок автоматических сообщений"
```

### Task 5: Сервис шаблонов — кэш, сохранение, сброс, отправка

**Files:**
- Create: `app/services/message_templates/keyboards.py`, `app/services/message_templates/service.py`
- Test: `tests/test_message_service.py`

**Interfaces:**
- Consumes: `get_event`, `EventDef` (Task 2), `render_template` (Task 3), `validate_template`, `validate_button_text` (Task 3), `MessageTemplate` (Task 4), `AsyncSessionLocal` из `app.database.database`, `settings.MINIAPP_URL`, `miniapp_url()` из `app.config`.
- Produces (`keyboards.py`):
  - `build_keyboard(key: str, label: str | None) -> InlineKeyboardMarkup | None` — клавиатура события с кнопкой (`winback`, `abandoned_payment` → кнопка оплаты; `welcome_nudge` → открытие приложения); `label is None` или событие без кнопки → `None`. Логика — та же, что была в `notification_service` (`_renew_button` и кнопка nudge).
- Produces (`service.py`):
  - `CACHE_TTL_SECONDS = 60.0`
  - `Override` (frozen dataclass): `key, template: str | None, button_text: str | None, enabled: bool, updated_at: datetime | None, updated_by_user_id: int | None`
  - `async load_overrides(db) -> dict[str, Override]` — читает правки из **переданной сессии** (для экранов редактора: видит и незакоммиченные изменения этой же сессии)
  - `async get_overrides(*, now: float | None = None) -> dict[str, Override]` (кэшированное чтение отдельной сессией); `invalidate_cache() -> None`
  - `TemplateValidationError(ValueError)` с атрибутом `errors: list[str]`
  - `async update_template(db, key, *, admin_user_id: int | None, template=UNSET, button_text=UNSET, enabled=UNSET) -> MessageTemplate` (частичное обновление: неуказанные поля не меняются; `template=None` — вернуть заводской текст; валидирует; **кэш сбрасывается после коммита сессии**, а не сразу — иначе читатели успели бы закэшировать старое, пока запись не видна; сам не коммитит)
  - `async reset_template(db, key, *, admin_user_id: int | None = None) -> bool` (удаляет строку; кэш сбрасывается после коммита; не коммитит; `True`, если строка была)
  - `Rendered` (frozen dataclass): `text, default_text, button_text: str | None, default_button_text: str | None, enabled: bool, is_custom: bool`
  - `compose(event, override: Override | None, variables) -> Rendered` (чистая функция)
  - `async render_message(key, **variables) -> Rendered`
  - `async build_preview(key, *, template: str | None = None, button_text: str | None = None) -> Rendered` — рендер с **примерами** переменных из реестра; переданные `template`/`button_text` заменяют текущие правки (без сохранения)
  - `is_template_error(error: TelegramBadRequest) -> bool`
  - `async send_templated(bot, *, telegram_id: int, key: str, **variables) -> None` — никогда не бросает исключение
  - `async send_test_message(bot, *, telegram_id: int, key: str, template=None, button_text=None) -> None` — отправляет предпросмотр; ошибки Telegram **пробрасываются** (`TelegramBadRequest`)
  - `UNSET` — sentinel для «поле не менять».

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_message_service.py`:

```python
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
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_message_service.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError: app.services.message_templates.service`).

- [ ] **Step 3: Клавиатуры**

Создайте `app/services/message_templates/keyboards.py`:

```python
"""Клавиатуры автоматических сообщений с кнопкой (winback, abandoned_payment, welcome_nudge).

Раньше жили в notification_service.py. Подпись кнопки приходит снаружи (заводская или правка владельца);
кнопка ведёт в Mini App, а без MINIAPP_URL — на прежний callback чат-сценария."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import miniapp_url, settings


def _renew_button(text: str) -> InlineKeyboardButton:
    """Ведёт сразу на экран оплаты Mini App, а не в чат-сценарий выбора тарифа. Пока MINIAPP_URL
    не задан — фолбэк на callback_data, тот же паттерн, что в kb_subscription_active."""
    if settings.MINIAPP_URL:
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=miniapp_url('/payment')))
    from app.keyboards.main_menu import CB_SUBSCRIPTION_RENEW

    return InlineKeyboardButton(text=text, callback_data=CB_SUBSCRIPTION_RENEW)


def _open_app_button(text: str) -> InlineKeyboardButton:
    """Дэшборд Mini App (не сразу /payment — пользователь ещё на триале); фолбэк — чат-сценарий 'sub:buy'."""
    if settings.MINIAPP_URL:
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=miniapp_url()))
    return InlineKeyboardButton(text=text, callback_data='sub:buy')


def build_keyboard(key: str, label: str | None) -> InlineKeyboardMarkup | None:
    if label is None:
        return None
    if key in ('winback', 'abandoned_payment'):
        return InlineKeyboardMarkup(inline_keyboard=[[_renew_button(label)]])
    if key == 'welcome_nudge':
        return InlineKeyboardMarkup(inline_keyboard=[[_open_app_button(label)]])
    return None
```

- [ ] **Step 4: Сервис**

Создайте `app/services/message_templates/service.py`:

```python
"""Правки автоматических сообщений: кэш, сохранение, сброс и отправка через шаблоны.

Заводские тексты — в registry.py, правки владельца — в таблице message_templates. Любая проблема с
правками (сбой БД, отказ Telegram из-за разметки/эмодзи) не должна терять уведомление: тогда уходит
заводской текст."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.database import AsyncSessionLocal
from app.database.models import MessageTemplate
from app.logging_setup import get_logger
from app.services.message_templates.keyboards import build_keyboard
from app.services.message_templates.registry import EventDef, get_event
from app.services.message_templates.render import render_template
from app.services.message_templates.validation import validate_button_text, validate_template

log = get_logger(__name__)
logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60.0
UNSET: object = object()  # «поле не менять» (None — осмысленное значение: вернуть заводской текст)

# Сообщения Telegram об ошибках разметки/эмодзи/длины — признак того, что виноват шаблон, а не получатель.
_TEMPLATE_ERROR_MARKERS = ('parse entities', 'entity', 'emoji', 'too long', 'text is empty')


@dataclass(frozen=True)
class Override:
    key: str
    template: str | None
    button_text: str | None
    enabled: bool
    updated_at: datetime | None
    updated_by_user_id: int | None


@dataclass(frozen=True)
class Rendered:
    text: str
    default_text: str
    button_text: str | None
    default_button_text: str | None
    enabled: bool
    is_custom: bool


class TemplateValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__('; '.join(errors))
        self.errors = errors


# --- кэш правок -------------------------------------------------------------------------------------------

_cache: dict[str, Override] | None = None
_loaded_at: float = 0.0


def invalidate_cache() -> None:
    global _cache, _loaded_at
    _cache = None
    _loaded_at = 0.0


async def load_overrides(db: AsyncSession) -> dict[str, Override]:
    """Правки из ПЕРЕДАННОЙ сессии (видит и её незакоммиченные изменения) — для экранов редактора."""
    rows = (await db.execute(select(MessageTemplate))).scalars().all()
    return {
        row.key: Override(row.key, row.template, row.button_text, row.enabled, row.updated_at, row.updated_by_user_id)
        for row in rows
    }


def _invalidate_after_commit(db: AsyncSession) -> None:
    """Кэш сбрасывается ПОСЛЕ коммита: до него запись видна только этой сессии, и читатель, перечитав БД
    раньше, закэшировал бы старое на целую минуту."""
    event.listen(db.sync_session, 'after_commit', lambda session: invalidate_cache(), once=True)


async def get_overrides(*, now: float | None = None) -> dict[str, Override]:
    """Правки владельца по ключам. Таблица маленькая (≤ 15 строк): кэш живёт CACHE_TTL_SECONDS и
    сбрасывается после коммита сохранения/сброса. Сбой БД → прошлый кэш либо пусто (заводские тексты)."""
    global _cache, _loaded_at
    current = time.monotonic() if now is None else now
    if _cache is not None and current - _loaded_at < CACHE_TTL_SECONDS:
        return _cache
    try:
        async with AsyncSessionLocal() as db:
            _cache = await load_overrides(db)
        _loaded_at = current
    except Exception:
        log.warning('templates_load_failed', exc_info=True)
    return _cache if _cache is not None else {}


# --- сохранение и сброс -----------------------------------------------------------------------------------


async def update_template(
    db: AsyncSession,
    key: str,
    *,
    admin_user_id: int | None,
    template: object = UNSET,
    button_text: object = UNSET,
    enabled: object = UNSET,
) -> MessageTemplate:
    """Частичное обновление правки. Валидирует; НЕ коммитит (коммит — на вызывающем), кэш сбрасывается после коммита."""
    event = get_event(key)  # неизвестный ключ -> UnknownEventError
    errors: list[str] = []
    if template is not UNSET and template is not None:
        errors += validate_template(event, str(template)).errors
    if button_text is not UNSET and button_text is not None:
        errors += validate_button_text(event, str(button_text))
    if errors:
        raise TemplateValidationError(errors)

    row = await db.get(MessageTemplate, key)
    if row is None:
        row = MessageTemplate(key=key, enabled=True)
        db.add(row)
    if template is not UNSET:
        row.template = template  # type: ignore[assignment]
    if button_text is not UNSET:
        row.button_text = button_text  # type: ignore[assignment]
    if enabled is not UNSET:
        row.enabled = bool(enabled)
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by_user_id = admin_user_id
    await db.flush()
    _invalidate_after_commit(db)
    log.info(
        'template_updated', key=key, admin_user_id=admin_user_id, customised=row.template is not None,
        enabled=row.enabled, length=len(row.template or ''),
    )
    return row


async def reset_template(db: AsyncSession, key: str, *, admin_user_id: int | None = None) -> bool:
    """Удаляет правку целиком (текст, кнопку, флаг). True, если она была. Коммит — на вызывающем (кэш сбросится после него)."""
    get_event(key)
    result = await db.execute(delete(MessageTemplate).where(MessageTemplate.key == key))
    _invalidate_after_commit(db)
    log.info('template_reset', key=key, admin_user_id=admin_user_id, existed=result.rowcount > 0)
    return result.rowcount > 0


# --- рендер -----------------------------------------------------------------------------------------------


def _miniapp_enabled() -> bool:
    return bool(settings.MINIAPP_URL)


def compose(event: EventDef, override: Override | None, variables: Mapping[str, object]) -> Rendered:
    default_text = render_template(event.default_template, variables)
    is_custom = bool(override and override.template is not None)
    text = render_template(override.template, variables) if is_custom else default_text  # type: ignore[union-attr,arg-type]
    default_button = event.button_label(_miniapp_enabled())
    button = None
    if event.has_button:
        button = override.button_text if override and override.button_text else default_button
    return Rendered(
        text=text,
        default_text=default_text,
        button_text=button,
        default_button_text=default_button,
        enabled=override.enabled if override else True,
        is_custom=is_custom,
    )


async def render_message(key: str, **variables: object) -> Rendered:
    event = get_event(key)
    overrides = await get_overrides()
    return compose(event, overrides.get(key), variables)


async def build_preview(key: str, *, template: str | None = None, button_text: str | None = None) -> Rendered:
    """Рендер с ПРИМЕРАМИ переменных. Переданные template/button_text заменяют текущие правки (не сохраняются)."""
    event = get_event(key)
    current = (await get_overrides()).get(key)
    override = Override(
        key=key,
        template=template if template is not None else (current.template if current else None),
        button_text=button_text if button_text is not None else (current.button_text if current else None),
        enabled=True,
        updated_at=None,
        updated_by_user_id=None,
    )
    return compose(event, override, event.samples())


# --- отправка ---------------------------------------------------------------------------------------------


def is_template_error(error: TelegramBadRequest) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _TEMPLATE_ERROR_MARKERS)


async def _deliver(bot: Bot, *, telegram_id: int, text: str, reply_markup) -> None:
    """Одна отправка. TelegramBadRequest пробрасывается (решает вызывающий); остальные ошибки
    гасятся, один повтор при flood-control — как в прежнем _safe_send."""
    try:
        await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
    except TelegramBadRequest:
        raise
    except TelegramRetryAfter as error:
        logger.warning('Flood control, жду %s сек и повторяю telegram_id=%s', error.retry_after, telegram_id)
        await asyncio.sleep(error.retry_after + 1)
        try:
            await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
        except Exception:
            logger.warning('Не удалось отправить уведомление telegram_id=%s (после ретрая)', telegram_id, exc_info=True)
    except Exception:
        logger.warning('Не удалось отправить уведомление telegram_id=%s', telegram_id, exc_info=True)


async def send_templated(bot: Bot, *, telegram_id: int, key: str, **variables: object) -> None:
    """Отправляет автоматическое сообщение по шаблону. НИКОГДА не бросает исключение: пользователь мог
    заблокировать бота, а сбой уведомления не должен ронять платёж или фоновую задачу."""
    try:
        rendered = await render_message(key, **variables)
    except Exception:
        logger.exception('Не удалось подготовить сообщение key=%s', key)
        return
    if not rendered.enabled:
        log.info('notification_skipped', key=key, telegram_id=telegram_id, reason='disabled')
        return

    try:
        await _deliver(bot, telegram_id=telegram_id, text=rendered.text, reply_markup=build_keyboard(key, rendered.button_text))
    except TelegramBadRequest as error:
        customised = rendered.is_custom or rendered.button_text != rendered.default_button_text
        if not (customised and is_template_error(error)):
            logger.warning('Не удалось отправить уведомление telegram_id=%s', telegram_id, exc_info=True)
            return
        log.warning('template_fallback', key=key, telegram_id=telegram_id, reason=str(error)[:200])
        try:
            await _deliver(
                bot, telegram_id=telegram_id, text=rendered.default_text,
                reply_markup=build_keyboard(key, rendered.default_button_text),
            )
        except Exception:
            logger.warning('Не удалось отправить заводской текст telegram_id=%s', telegram_id, exc_info=True)


async def send_test_message(
    bot: Bot, *, telegram_id: int, key: str, template: str | None = None, button_text: str | None = None
) -> None:
    """Отправляет предпросмотр (с примерами переменных). Ошибки Telegram НЕ гасятся — админ должен
    увидеть причину (например, недопустимое кастомное эмодзи)."""
    rendered = await build_preview(key, template=template, button_text=button_text)
    await bot.send_message(
        chat_id=telegram_id, text=rendered.text, reply_markup=build_keyboard(key, rendered.button_text)
    )
```

- [ ] **Step 4b: Изоляция кэша правок во всех тестах**

С этого момента любое уведомление (в том числе из платёжных и фоновых тестов) обращается к кэшу правок; без изоляции оно полезло бы в БД приложения (`sqlite:///:memory:` без таблиц). Добавьте в `tests/conftest.py` (модуль `service` уже существует):

```python
@pytest.fixture(autouse=True)
def no_template_overrides(monkeypatch):
    """Автоуведомления по умолчанию шлют заводские тексты: кэш правок «пуст навсегда», БД не трогаем.
    Тесты шаблонов сбрасывают кэш сами (invalidate_cache) и работают с настоящей таблицей."""
    from app.services.message_templates import service

    monkeypatch.setattr(service, '_cache', {})
    monkeypatch.setattr(service, '_loaded_at', float('inf'))
```

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests/test_message_service.py -q -p no:warnings` → PASS; затем весь набор (проверьте, что прежние 199 тестов и характеризационные тесты Task 1 проходят).
Замечание: `get_overrides(now=…)` в тестах кэша использует искусственное монотонное время; `invalidate_cache()` сбрасывается фикстурой `use_test_db` до и после каждого теста.

- [ ] **Step 6: Мутации**

По одной, каждая роняет тест, затем откат: убрать `_invalidate_after_commit(db)` из `update_template` (упадёт `test_cache_is_refreshed_only_after_commit`); заменить `event.listen(..., 'after_commit', ...)` на немедленный `invalidate_cache()` (упадёт тот же тест); убрать `is_template_error(error)` из условия отката (упадёт `test_unrelated_bad_request…`); убрать `customised` из условия (упадёт повторная отправка при обычной ошибке); заменить `if not rendered.enabled` на `if False` (упадёт `test_disabled_event_sends_nothing`).

- [ ] **Step 7: Коммит**

```bash
git add app/services/message_templates/keyboards.py app/services/message_templates/service.py tests/test_message_service.py tests/conftest.py
git commit -m "Добавляет сервис шаблонов сообщений: кэш, сохранение, отправка с откатом на заводской текст"
```

---

### Task 6: Перевод `notify_*` на шаблоны

**Files:**
- Modify: `app/services/notification_service.py` (переписать целиком)
- Test: `tests/test_notifications_templated.py`; `tests/test_notifications_golden.py` (Task 1) обязан пройти без правок.

**Interfaces:**
- Consumes: `send_templated` (Task 5).
- Produces: те же 14 функций `notify_*` с прежними сигнатурами (`notify_payment_success(bot, *, telegram_id, amount_kopeks, description)`, `notify_referral_bonus(bot, *, telegram_id, amount_kopeks)`, `notify_referral_invite_bonus(bot, *, telegram_id, bonus_days)`, `notify_subscription_expiring(bot, *, telegram_id, days_left)`, `notify_subscription_expired(bot, *, telegram_id)`, `notify_gift_redeemed_to_gifter(bot, *, gifter_telegram_id, recipient_username)`, `notify_gift_code_ready(bot, *, telegram_id, link)`, `notify_balance_changed(bot, *, telegram_id, amount_kopeks, new_balance_kopeks)`, `notify_autopay_activated/charge_failed/stopped(bot, *, telegram_id)`, `notify_winback/abandoned_payment/welcome_nudge(bot, *, telegram_id)`).

- [ ] **Step 1: Убедиться, что характеризационные тесты проходят ДО правки**

Run: `python -m pytest tests/test_notifications_golden.py -q -p no:warnings` → PASS (базовая линия).

- [ ] **Step 2: Проверить, кто импортирует из модуля**

Run: `grep -rn "notification_service import\|_safe_send\|_renew_button" app tests scripts --include=*.py`
Expected: импортируются только имена `notify_*` (и комментарий в `background.py` про `_safe_send`); `_safe_send` и `_renew_button` больше нигде не используются. Если нашлись другие потребители — оставьте эти функции, продублировав/перенаправив их.

- [ ] **Step 3: Падающие тесты на новое поведение**

Создайте `tests/test_notifications_templated.py`:

```python
"""notify_* используют правки владельца: свой текст, выключение, откат на заводской текст, кнопки."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.config import settings
from app.database.models import MessageTemplate
from app.services import notification_service as ns
from app.services.message_templates import service
from app.services.message_templates.service import invalidate_cache

CHAT = 42


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(service, 'AsyncSessionLocal', session_factory)
    invalidate_cache()
    yield
    invalidate_cache()


async def _set(factory, key: str, **fields) -> None:
    async with factory() as db:
        db.add(MessageTemplate(key=key, **fields))
        await db.commit()
    invalidate_cache()


def test_custom_payment_text_is_used_and_values_are_escaped(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'payment_success', template='🧾 {amount}₽ — <b>{description}</b>')
        await ns.notify_payment_success(bot, telegram_id=CHAT, amount_kopeks=24900, description='Тариф <VIP> & Co')

    asyncio.run(scenario())

    assert bot.send_message.await_args.kwargs['text'] == '🧾 249.00₽ — <b>Тариф &lt;VIP&gt; &amp; Co</b>'


def test_balance_change_picks_credit_or_debit_template(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'balance_credited', template='+{amount} (итого {balance})')
        await _set(session_factory, 'balance_debited', template='-{amount} (итого {balance})')
        await ns.notify_balance_changed(bot, telegram_id=CHAT, amount_kopeks=10000, new_balance_kopeks=35000)
        await ns.notify_balance_changed(bot, telegram_id=CHAT, amount_kopeks=-5000, new_balance_kopeks=30000)

    asyncio.run(scenario())

    assert [call.kwargs['text'] for call in bot.send_message.await_args_list] == ['+100.00 (итого 350.00)', '-50.00 (итого 300.00)']


def test_gift_redeemed_variable_who(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'gift_redeemed', template='🎁 {who} принял подарок')
        await ns.notify_gift_redeemed_to_gifter(bot, gifter_telegram_id=CHAT, recipient_username=None)
        await ns.notify_gift_redeemed_to_gifter(bot, gifter_telegram_id=CHAT, recipient_username='friend')

    asyncio.run(scenario())

    assert [call.kwargs['text'] for call in bot.send_message.await_args_list] == ['🎁 пользователь принял подарок', '🎁 @friend принял подарок']


def test_disabled_event_is_not_sent(session_factory):
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'subscription_expiring', enabled=False)
        await ns.notify_subscription_expiring(bot, telegram_id=CHAT, days_left=3)

    asyncio.run(scenario())

    bot.send_message.assert_not_awaited()


def test_broken_template_falls_back_to_the_legacy_text(session_factory):
    bot = AsyncMock()
    bot.send_message.side_effect = [TelegramBadRequest(method=SendMessage(chat_id=CHAT, text='x'), message="can't parse entities"), None]

    async def scenario():
        await _set(session_factory, 'subscription_expired', template='<b>без закрытия')
        await ns.notify_subscription_expired(bot, telegram_id=CHAT)

    asyncio.run(scenario())

    assert bot.send_message.await_args.kwargs['text'] == '❌ Ваша подписка истекла. Продлите её в главном меню.'


def test_button_events_use_custom_label_but_keep_the_action(session_factory, monkeypatch):
    monkeypatch.setattr(settings, 'MINIAPP_URL', '')
    bot = AsyncMock()

    async def scenario():
        await _set(session_factory, 'welcome_nudge', button_text='Погнали', template='Привет, друг')
        await ns.notify_welcome_nudge(bot, telegram_id=CHAT)

    asyncio.run(scenario())

    button = bot.send_message.await_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert (button.text, button.callback_data) == ('Погнали', 'sub:buy')
    assert bot.send_message.await_args.kwargs['text'] == 'Привет, друг'


def test_database_failure_still_sends_default_text(monkeypatch):
    monkeypatch.setattr(service, 'AsyncSessionLocal', lambda: (_ for _ in ()).throw(RuntimeError('db down')))
    bot = AsyncMock()

    asyncio.run(ns.notify_autopay_activated(bot, telegram_id=CHAT))

    assert bot.send_message.await_args.kwargs['text'].startswith('🔄 Автоплатёж подключён')
```

Run: `python -m pytest tests/test_notifications_templated.py -q -p no:warnings`
Expected: FAIL (старые `notify_*` игнорируют правки).

- [ ] **Step 4: Переписать `notification_service.py`**

Замените содержимое `app/services/notification_service.py` целиком:

```python
"""Автоматические сообщения бота пользователям. Вызывается из subscription.py (успешная оплата),
referral_service.py (бонус рефереру), gift_service.py (подарок активирован), background-задач
(напоминания), webhooks.py (автоплатёж).

Тексты живут в реестре шаблонов (app/services/message_templates/registry.py) и могут быть изменены
владельцем в админке (таблица message_templates); здесь — тонкие обёртки с ПРЕЖНИМИ сигнатурами
(другие модули вызывают их «на веру» — не менять). Пользователь мог заблокировать бота или удалить чат —
это НЕ должно ронять вызывающий код (платёж, начисление, фоновая задача), поэтому send_templated
никогда не бросает исключение и при сбое шаблона шлёт заводской текст."""

from __future__ import annotations

from aiogram import Bot

from app.services.message_templates.service import send_templated


def _rub(kopeks: int) -> str:
    """Сумма в рублях числом без знака ₽ (знак остаётся в тексте шаблона): 24900 -> '249.00'."""
    return f'{kopeks / 100:.2f}'


async def notify_payment_success(bot: Bot, *, telegram_id: int, amount_kopeks: int, description: str) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='payment_success', amount=_rub(amount_kopeks), description=description)


async def notify_referral_bonus(bot: Bot, *, telegram_id: int, amount_kopeks: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='referral_bonus', amount=_rub(amount_kopeks))


async def notify_referral_invite_bonus(bot: Bot, *, telegram_id: int, bonus_days: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='referral_invite_bonus', bonus_days=bonus_days)


async def notify_subscription_expiring(bot: Bot, *, telegram_id: int, days_left: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='subscription_expiring', days_left=days_left)


async def notify_subscription_expired(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='subscription_expired')


async def notify_gift_redeemed_to_gifter(bot: Bot, *, gifter_telegram_id: int, recipient_username: str | None) -> None:
    who = f'@{recipient_username}' if recipient_username else 'пользователь'
    await send_templated(bot, telegram_id=gifter_telegram_id, key='gift_redeemed', who=who)


async def notify_gift_code_ready(bot: Bot, *, telegram_id: int, link: str) -> None:
    """Платёж за подарок подтверждён асинхронно (payment_poll_loop) — исходное сообщение бота уже
    недоступно для редактирования, поэтому шлём новое."""
    await send_templated(bot, telegram_id=telegram_id, key='gift_code_ready', link=link)


async def notify_balance_changed(bot: Bot, *, telegram_id: int, amount_kopeks: int, new_balance_kopeks: int) -> None:
    """Ручное начисление/списание баланса администратором — без имени админа в тексте для пользователя."""
    key = 'balance_credited' if amount_kopeks > 0 else 'balance_debited'
    await send_templated(bot, telegram_id=telegram_id, key=key, amount=_rub(abs(amount_kopeks)), balance=_rub(new_balance_kopeks))


async def notify_autopay_activated(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='autopay_activated')


async def notify_autopay_charge_failed(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='autopay_charge_failed')


async def notify_autopay_stopped(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='autopay_stopped')


# === Автоматические триггеры рассылок (app/services/background.py): вызываются фоновыми циклами по
# условию времени/состояния. Кнопка ведёт в конкретный экран Mini App — её подпись (заводская или
# правка владельца) и действие собирает app/services/message_templates/keyboards.py. ===


async def notify_winback(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='winback')


async def notify_abandoned_payment(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='abandoned_payment')


async def notify_welcome_nudge(bot: Bot, *, telegram_id: int) -> None:
    await send_templated(bot, telegram_id=telegram_id, key='welcome_nudge')
```

- [ ] **Step 5: Все тесты проходят**

Run: `python -m pytest tests/test_notifications_golden.py tests/test_notifications_templated.py -q -p no:warnings` → PASS (характеризационные тесты Task 1 проходят **без изменений**: это доказательство, что тексты и клавиатуры не изменились).
Затем `python -m pytest tests -q -p no:warnings` → PASS (все прежние 199 + новые).
Если упал характеризационный тест — расхождение заводского текста в реестре с прежним: исправляйте реестр (Task 2), а не тест.

- [ ] **Step 6: Импорт-проверка**

Run: `python -c "import os;os.environ['BOT_TOKEN']='1:t'; import main; print('import ok')"` → `import ok` (проверяет, что нет циклических импортов между `notification_service`, `service`, `keyboards`).

- [ ] **Step 7: Мутации**

Замените в `notify_balance_changed` `amount_kopeks > 0` на `>= 0` — падает характеризация `balance_zero_amount_is_treated_as_debit`; поменяйте условие на `< 0` — падают оба теста выбора шаблона; уберите `abs(` — падает тест `balance_debited`; в `_rub` замените `.2f` на `.1f` — падают golden-тесты.

- [ ] **Step 8: Коммит**

```bash
git add app/services/notification_service.py tests/test_notifications_templated.py
git commit -m "Переводит автоматические уведомления на шаблоны с откатом на заводской текст"
```

### Task 7: API `/cabinet/admin/notifications/*`

**Files:**
- Create: `app/cabinet/notifications_schemas.py`, `app/cabinet/notifications_routes.py`
- Modify: `app/cabinet/app.py`
- Test: `tests/test_notifications_api.py`

**Interfaces:**
- Consumes: `EVENTS`, `get_event`, `UnknownEventError` (Task 2), `validate_template`, `validate_button_text` (Task 3), `MessageTemplate` (Task 4), `update_template`, `reset_template`, `build_preview`, `send_test_message`, `get_overrides`, `TemplateValidationError`, `UNSET` (Task 5), `require_admin` из `app.cabinet.admin_deps`, `get_db` из `app.cabinet.deps`, `app.emoji`.
- Produces (HTTP, `require_admin`):
  - `GET /templates` → `list[TemplateOut]` (порядок реестра).
  - `PUT /templates/{key}` (тело `TemplateUpdateRequest`, **частичное**: применяются только переданные поля; `template: null` возвращает заводской текст) → `TemplateOut`; `404` неизвестный ключ; `422` ошибки проверок.
  - `DELETE /templates/{key}` → `{"status": "reset", "was_customized": bool}`; `404` неизвестный ключ.
  - `POST /templates/{key}/preview` (тело `PreviewRequest`) → `PreviewResponse`; `422` при ошибках.
  - `POST /templates/{key}/test` (тело `PreviewRequest`) → `{"status": "sent"}`; `502` при отказе Telegram (с текстом причины).
  - `GET /emoji` → `list[EmojiOut]`.
- Формат `422`: `{"detail": [{"loc": ["body"], "msg": "<текст>", "type": "template_invalid"}, ...]}`.

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_notifications_api.py`:

```python
"""API редактирования шаблонов сообщений."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cabinet.admin_deps import require_admin
from app.cabinet.app import create_app
from app.cabinet.deps import get_db
from app.database.models import User
from app.services.message_templates import service
from app.services.message_templates.registry import EVENTS
from app.services.message_templates.service import get_overrides, invalidate_cache
from tests.helpers import make_user

BASE = '/cabinet/admin/notifications'


@pytest.fixture
def api(session_factory, monkeypatch):
    monkeypatch.setattr(service, 'AsyncSessionLocal', session_factory)
    invalidate_cache()
    admin_id = asyncio.run(make_user(session_factory, telegram_id=555, username='boss', is_admin=True))
    engine = create_async_engine(str(session_factory.kw['bind'].url), connect_args={'timeout': 30})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    bot = AsyncMock()
    app = create_app(bot)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: User(id=admin_id, telegram_id=555, referral_code='a', is_admin=True)
    with TestClient(app) as client:
        client.bot = bot
        client.admin_id = admin_id
        yield client
    invalidate_cache()


def _by_key(client) -> dict:
    return {item['key']: item for item in client.get(f'{BASE}/templates').json()}


def test_list_returns_all_events_with_frontend_contract_fields(api):
    response = api.get(f'{BASE}/templates')

    assert response.status_code == 200
    items = response.json()
    assert [item['key'] for item in items] == [event.key for event in EVENTS]
    payment = items[0]
    assert {'key', 'group', 'title', 'trigger', 'template', 'variables'} <= set(payment)  # поля, которые уже знает фронтенд
    assert payment['variables'] == ['amount', 'description']
    assert payment['template'] == payment['default_template'] and payment['is_customized'] is False and payment['enabled'] is True
    assert payment['variable_docs'][0] == {'name': 'amount', 'description': 'Сумма в рублях числом, без знака ₽ (например 249.00)', 'example': '249.00'}
    assert payment['button_text'] is None and payment['required_variables'] == []
    gift = next(item for item in items if item['key'] == 'gift_code_ready')
    assert gift['required_variables'] == ['link']
    winback = next(item for item in items if item['key'] == 'winback')
    assert winback['button_text'] == winback['default_button_text'] == '💎 Возобновить подписку'


def test_admin_required():
    app = create_app(AsyncMock())
    with TestClient(app) as client:
        assert client.get(f'{BASE}/templates').status_code == 401


def test_put_saves_text_and_takes_effect_immediately(api, session_factory):  # кэш сбрасывается после коммита запроса
    response = api.put(f'{BASE}/templates/payment_success', json={'template': '🧾 <b>{amount}₽</b> — {description}'})

    assert response.status_code == 200
    body = response.json()
    assert body['template'] == '🧾 <b>{amount}₽</b> — {description}' and body['is_customized'] is True
    assert body['updated_by'] == 'boss' and body['updated_at'] is not None
    assert asyncio.run(get_overrides())['payment_success'].template == '🧾 <b>{amount}₽</b> — {description}'
    assert _by_key(api)['payment_success']['is_customized'] is True


def test_put_invalid_template_is_422_with_messages_and_saves_nothing(api):
    response = api.put(f'{BASE}/templates/payment_success', json={'template': '<script>x</script> {nope}'})

    assert response.status_code == 422
    detail = response.json()['detail']
    assert isinstance(detail, list) and all({'loc', 'msg', 'type'} <= set(entry) for entry in detail)
    assert any('{nope}' in entry['msg'] for entry in detail)
    assert _by_key(api)['payment_success']['is_customized'] is False


def test_put_is_partial(api):
    api.put(f'{BASE}/templates/winback', json={'template': 'Возвращайтесь!', 'button_text': 'Вернуться'})

    api.put(f'{BASE}/templates/winback', json={'enabled': False})
    after_disable = _by_key(api)['winback']
    api.put(f'{BASE}/templates/winback', json={'template': None})
    after_reset_text = _by_key(api)['winback']

    assert (after_disable['template'], after_disable['button_text'], after_disable['enabled']) == ('Возвращайтесь!', 'Вернуться', False)
    assert after_reset_text['is_customized'] is False and after_reset_text['template'] == after_reset_text['default_template']
    assert after_reset_text['button_text'] == 'Вернуться' and after_reset_text['enabled'] is False


def test_put_errors_for_unknown_key_and_button_on_event_without_button(api):
    assert api.put(f'{BASE}/templates/no_such', json={'template': 'x'}).status_code == 404
    assert api.put(f'{BASE}/templates/subscription_expired', json={'button_text': 'кнопки нет'}).status_code == 422
    assert api.put(f'{BASE}/templates/winback', json={'button_text': '<b>x</b>'}).status_code == 422


def test_delete_resets_everything_and_is_idempotent(api):
    api.put(f'{BASE}/templates/winback', json={'template': 'Привет', 'enabled': False})

    first = api.delete(f'{BASE}/templates/winback')
    second = api.delete(f'{BASE}/templates/winback')

    assert first.json() == {'status': 'reset', 'was_customized': True}
    assert second.json() == {'status': 'reset', 'was_customized': False}
    item = _by_key(api)['winback']
    assert item['is_customized'] is False and item['enabled'] is True
    assert api.delete(f'{BASE}/templates/no_such').status_code == 404


def test_preview_renders_examples_without_saving(api):
    response = api.post(f'{BASE}/templates/payment_success/preview', json={'template': '<b>{amount}</b>₽ {description}'})

    assert response.status_code == 200
    body = response.json()
    assert body['html'] == '<b>249.00</b>₽ Подписка «Онлайн» на 30 дн.'
    assert body['visible_length'] == len('249.00₽ Подписка «Онлайн» на 30 дн.') and body['warnings'] == []
    assert _by_key(api)['payment_success']['is_customized'] is False


def test_preview_of_current_text_and_of_invalid_text(api):
    current = api.post(f'{BASE}/templates/subscription_expired/preview', json={})
    invalid = api.post(f'{BASE}/templates/subscription_expired/preview', json={'template': '<b>не закрыт'})

    assert current.status_code == 200 and current.json()['html'].startswith('❌ Ваша подписка истекла')
    assert invalid.status_code == 422


def test_preview_warns_about_custom_emoji(api):
    body = api.post(
        f'{BASE}/templates/subscription_expired/preview',
        json={'template': '<tg-emoji emoji-id="5368446439800197476">🏦</tg-emoji> конец'},
    ).json()

    assert any('Тест' in warning for warning in body['warnings'])


def test_test_send_goes_to_the_calling_admin(api):
    response = api.post(f'{BASE}/templates/payment_success/test', json={'template': 'Тест {amount}'})

    assert response.status_code == 200 and response.json() == {'status': 'sent'}
    kwargs = api.bot.send_message.await_args.kwargs
    assert kwargs['chat_id'] == 555 and kwargs['text'] == 'Тест 249.00'


def test_test_send_reports_telegram_rejection(api):
    api.bot.send_message.side_effect = TelegramBadRequest(
        method=SendMessage(chat_id=555, text='x'), message='Bad Request: ENTITY_TEXT_INVALID'
    )

    response = api.post(
        f'{BASE}/templates/subscription_expired/test',
        json={'template': '<tg-emoji emoji-id="1">🏦</tg-emoji> конец'},
    )

    assert response.status_code == 502 and 'ENTITY_TEXT_INVALID' in response.json()['detail']


def test_test_send_rejects_invalid_template_before_sending(api):
    response = api.post(f'{BASE}/templates/subscription_expired/test', json={'template': '<b>не закрыт'})

    assert response.status_code == 422
    api.bot.send_message.assert_not_awaited()


def test_emoji_slots_list(api):
    response = api.get(f'{BASE}/emoji')

    assert response.status_code == 200
    slots = {slot['name']: slot for slot in response.json()}
    assert slots['SBP']['custom_id'] == '5368446439800197476' and slots['SBP']['fallback'] == '🏦'
    assert all(slot['custom_id'] for slot in slots.values())  # только слоты с заданным ID
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_notifications_api.py -q -p no:warnings`
Expected: FAIL (404 на всех путях / нет роутера).

- [ ] **Step 3: Схемы**

Создайте `app/cabinet/notifications_schemas.py`:

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VariableDocOut(BaseModel):
    name: str
    description: str
    example: str


class TemplateOut(BaseModel):
    key: str
    group: str
    title: str
    trigger: str
    template: str  # текущий текст: правка владельца либо заводской
    variables: list[str]
    default_template: str
    is_customized: bool
    enabled: bool
    button_text: str | None = None  # текущая подпись кнопки (None, если у события нет кнопки)
    default_button_text: str | None = None
    variable_docs: list[VariableDocOut]
    required_variables: list[str]
    updated_at: datetime | None = None
    updated_by: str | None = None


class TemplateUpdateRequest(BaseModel):
    """Частичное обновление: применяются только переданные поля. `template: null` возвращает заводской текст,
    `button_text: null` — заводскую подпись кнопки."""

    template: str | None = None
    button_text: str | None = None
    enabled: bool | None = None


class PreviewRequest(BaseModel):
    template: str | None = None  # None — текущий текст
    button_text: str | None = None  # None — текущая подпись


class PreviewResponse(BaseModel):
    html: str
    visible_length: int
    warnings: list[str]
    button_text: str | None = None


class EmojiOut(BaseModel):
    name: str
    fallback: str
    custom_id: str
```

- [ ] **Step 4: Маршруты**

Создайте `app/cabinet/notifications_routes.py`:

```python
"""/cabinet/admin/notifications/* — редактирование текстов автоматических сообщений бота."""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.emoji as emoji_module
from app.cabinet.admin_deps import require_admin
from app.cabinet.deps import get_db
from app.cabinet.notifications_schemas import (
    EmojiOut,
    PreviewRequest,
    PreviewResponse,
    TemplateOut,
    TemplateUpdateRequest,
    VariableDocOut,
)
from app.config import settings
from app.database.models import MessageTemplate, User
from app.services.message_templates.registry import EVENTS, EventDef, UnknownEventError, get_event
from app.services.message_templates.service import (
    UNSET,
    TemplateValidationError,
    build_preview,
    reset_template,
    send_test_message,
    update_template,
)
from app.services.message_templates.validation import validate_button_text, validate_template

router = APIRouter(prefix='/cabinet/admin/notifications')


def _event_or_404(key: str) -> EventDef:
    try:
        return get_event(key)
    except UnknownEventError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Событие не найдено') from None


def _unprocessable(errors: list[str]) -> HTTPException:
    detail = [{'loc': ['body'], 'msg': message, 'type': 'template_invalid'} for message in errors]
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


def _author_name(user: User | None) -> str | None:
    if user is None:
        return None
    return user.username or user.full_name or str(user.telegram_id)


def _to_out(event: EventDef, row: MessageTemplate | None, author: User | None) -> TemplateOut:
    miniapp = bool(settings.MINIAPP_URL)
    default_button = event.button_label(miniapp)
    customised = row is not None and row.template is not None
    button = None
    if event.has_button:
        button = row.button_text if row is not None and row.button_text else default_button
    return TemplateOut(
        key=event.key,
        group=event.group,
        title=event.title,
        trigger=event.trigger,
        template=row.template if customised else event.default_template,  # type: ignore[union-attr]
        variables=list(event.variable_names),
        default_template=event.default_template,
        is_customized=customised,
        enabled=row.enabled if row is not None else True,
        button_text=button,
        default_button_text=default_button,
        variable_docs=[VariableDocOut(name=v.name, description=v.description, example=v.example) for v in event.variables],
        required_variables=list(event.required_variables),
        updated_at=row.updated_at if row is not None else None,
        updated_by=_author_name(author),
    )


async def _load_all(db: AsyncSession) -> list[TemplateOut]:
    rows = {row.key: row for row in (await db.execute(select(MessageTemplate))).scalars()}
    author_ids = {row.updated_by_user_id for row in rows.values() if row.updated_by_user_id is not None}
    authors: dict[int, User] = {}
    if author_ids:
        authors = {user.id: user for user in (await db.execute(select(User).where(User.id.in_(author_ids)))).scalars()}
    return [
        _to_out(event, rows.get(event.key), authors.get(rows[event.key].updated_by_user_id) if event.key in rows else None)
        for event in EVENTS
    ]


async def _load_one(db: AsyncSession, key: str) -> TemplateOut:
    return next(item for item in await _load_all(db) if item.key == key)


@router.get('/templates', response_model=list[TemplateOut])
async def list_templates(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> list[TemplateOut]:
    return await _load_all(db)


@router.put('/templates/{key}', response_model=TemplateOut)
async def put_template(
    key: str,
    payload: TemplateUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> TemplateOut:
    _event_or_404(key)
    fields = {}
    if 'template' in payload.model_fields_set:
        fields['template'] = payload.template
    if 'button_text' in payload.model_fields_set:
        fields['button_text'] = payload.button_text
    if payload.enabled is not None:
        fields['enabled'] = payload.enabled
    try:
        await update_template(db, key, admin_user_id=admin.id, **fields)
    except TemplateValidationError as error:
        raise _unprocessable(error.errors) from error
    await db.commit()
    return await _load_one(db, key)


@router.delete('/templates/{key}')
async def delete_template(
    key: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    _event_or_404(key)
    existed = await reset_template(db, key, admin_user_id=admin.id)
    await db.commit()
    return {'status': 'reset', 'was_customized': existed}


async def _validated_preview(db: AsyncSession, key: str, event: EventDef, payload: PreviewRequest):
    """Проверяет текст и подпись (те же правила, что при сохранении) и собирает рендер с примерами."""
    errors: list[str] = []
    result = None
    if payload.template is not None:
        result = validate_template(event, payload.template)
        errors += result.errors
    if payload.button_text is not None:
        errors += validate_button_text(event, payload.button_text)
    if errors:
        raise _unprocessable(errors)
    rendered = await build_preview(key, template=payload.template, button_text=payload.button_text)
    if result is None:  # текущий текст: считаем длину и предупреждения по нему
        current = next(item for item in await _load_all(db) if item.key == key)
        result = validate_template(event, current.template)
    return rendered, result


@router.post('/templates/{key}/preview', response_model=PreviewResponse)
async def preview_template(
    key: str, payload: PreviewRequest, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> PreviewResponse:
    event = _event_or_404(key)
    rendered, result = await _validated_preview(db, key, event, payload)
    return PreviewResponse(
        html=rendered.text, visible_length=result.visible_length, warnings=result.warnings, button_text=rendered.button_text
    )


@router.post('/templates/{key}/test')
async def test_template(
    key: str,
    payload: PreviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Отправляет предпросмотр (с примерами переменных) вызвавшему админу в Telegram."""
    event = _event_or_404(key)
    await _validated_preview(db, key, event, payload)
    try:
        await send_test_message(
            request.app.state.bot, telegram_id=admin.telegram_id, key=key,
            template=payload.template, button_text=payload.button_text,
        )
    except TelegramBadRequest as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f'Telegram отклонил сообщение: {error.message}') from error
    except Exception as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, 'Не удалось отправить тестовое сообщение') from error
    return {'status': 'sent'}


@router.get('/emoji', response_model=list[EmojiOut])
async def list_emoji(_admin: User = Depends(require_admin)) -> list[EmojiOut]:
    """Кастомные эмодзи из app/emoji.py с заданным custom_id — для вставки в текст через <tg-emoji emoji-id="…">."""
    slots = [
        EmojiOut(name=name, fallback=value.fallback, custom_id=value.custom_id)
        for name, value in sorted(vars(emoji_module).items())
        if isinstance(value, emoji_module.Emoji) and value.custom_id
    ]
    return slots
```

В `app/cabinet/app.py` добавьте импорт `from app.cabinet.notifications_routes import router as notifications_router` и после `app.include_router(admin_router)` строку `app.include_router(notifications_router)`.

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests/test_notifications_api.py -q -p no:warnings` → PASS; затем весь набор.
Если `test_admin_required` возвращает не 401 — проверьте, что роутер использует `Depends(require_admin)` на каждом эндпоинте.

- [ ] **Step 6: Мутации**

По одной, каждая роняет тест, затем откат: убрать `'template' in payload.model_fields_set` (упадёт `test_put_is_partial`); убрать вызов проверок в `_validated_preview` (упадёт `test_test_send_rejects_invalid_template_before_sending`); убрать `await db.commit()` в `put_template` (упадёт проверка применения и ответ), убрать `_load_one(...)` и вернуть данные из запроса (упадёт проверка `updated_by`).

- [ ] **Step 7: Коммит**

```bash
git add app/cabinet/notifications_schemas.py app/cabinet/notifications_routes.py app/cabinet/app.py tests/test_notifications_api.py
git commit -m "Добавляет API редактирования шаблонов сообщений: список, сохранение, сброс, предпросмотр, тест"
```

---

### Task 8: Редактор в боте (`/admin` → «✉️ Сообщения»)

**Files:**
- Create: `app/handlers/message_templates_admin.py`
- Modify: `app/states.py`, `app/handlers/admin.py` (`_root_keyboard`), `app/handlers/__init__.py`
- Test: `tests/test_message_templates_bot.py`

**Interfaces:**
- Consumes: сервис и проверки (Tasks 2–5): `load_overrides`, `compose`, `build_preview`, `update_template`, `reset_template`, `send_test_message`, `validate_template`, `validate_button_text`; из `app/handlers/admin.py`: `CB_ADMIN_ROOT`, `_answer_or_edit(callback, text, keyboard)`, `_back_keyboard(callback_data, text)`, `_is_admin(db_user)`.
- Produces: `AdminTemplateStates` (`entering_text`, `confirming`, `entering_button`); роутер `router = Router(name='message_templates_admin')` и `register_handlers(dp)`; callback-префикс `tpl:`: `tpl:root`, `tpl:card:<key>`, `tpl:edit:<key>`, `tpl:btn:<key>`, `tpl:toggle:<key>`, `tpl:reset:<key>`, `tpl:test:<key>`, `tpl:save`, `tpl:cancel:<key>`.
- Поведение:
  - Вводимый админом текст берётся из `message.html_text` (форматирование и `custom_emoji` уже превращены в HTML/`<tg-emoji>`).
  - **Экраны читают состояние из сессии обработчика** (`load_overrides(db)`), а не из общего кэша: сообщение о сохранении показывает свежие данные ещё до коммита (его делает `AuthMiddleware` после обработчика), а кэш сбрасывается после коммита (см. Task 5).
  - Карточка показывает текст **без** тегов `<tg-emoji>` (остаётся символ-заменитель), чтобы отображение не зависело от Premium; настоящий вид проверяется кнопкой «Тест мне».
  - Подпись кнопки: символ `-` возвращает заводскую.

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_message_templates_bot.py`:

```python
"""Редактор шаблонов сообщений в админке бота (обработчики вызываются напрямую)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, MessageEntity

from app.database.models import MessageTemplate, User
from app.handlers import message_templates_admin as h
from app.handlers import register_all_handlers
from app.handlers.admin import _root_keyboard
from app.services.message_templates import service
from app.services.message_templates.registry import EVENTS
from app.services.message_templates.service import get_overrides, invalidate_cache
from app.states import AdminTemplateStates
from tests.helpers import make_user

ADMIN_TG = 555


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(service, 'AsyncSessionLocal', session_factory)
    invalidate_cache()
    yield
    invalidate_cache()


def _state() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=ADMIN_TG, user_id=ADMIN_TG))


def _callback(data: str):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=ADMIN_TG),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
        bot=AsyncMock(),
    )


def _message(html_text: str):
    return SimpleNamespace(html_text=html_text, text=html_text, answer=AsyncMock())


def _admin(admin_id: int) -> User:
    return User(id=admin_id, telegram_id=ADMIN_TG, referral_code='a', is_admin=True)


def _shown(callback) -> tuple[str, object]:
    """(текст, клавиатура) последнего показанного экрана (edit_text либо answer)."""
    for method in (callback.message.edit_text, callback.message.answer):
        if method.await_args is not None:
            args, kwargs = method.await_args
            return args[0], kwargs.get('reply_markup')
    raise AssertionError('экран не показан')


def _buttons(markup) -> list:
    return [button for row in markup.inline_keyboard for button in row]


async def _run(session_factory, handler, *args, commit: bool = True):
    """Вызывает обработчик в своей сессии и коммитит её — как AuthMiddleware после хендлера."""
    async with session_factory() as db:
        result = await handler(*[db if arg is None else arg for arg in args])
        if commit:
            await db.commit()
        return result


def test_root_button_exists_in_admin_menu_and_router_is_registered():
    callbacks = [button.callback_data for button in _buttons(_root_keyboard())]
    dispatcher = Dispatcher()
    register_all_handlers(dispatcher)

    assert h.CB_ROOT in callbacks
    assert 'message_templates_admin' in [router.name for router in dispatcher.sub_routers]


def test_non_admin_is_ignored(session_factory):
    async def scenario():
        callback = _callback(h.CB_ROOT)
        stranger = User(id=9, telegram_id=1, referral_code='x', is_admin=False)

        await _run(session_factory, h.cb_root, callback, None, stranger, _state())

        callback.message.edit_text.assert_not_awaited()
        callback.message.answer.assert_not_awaited()

    asyncio.run(scenario())


def test_root_lists_all_events_with_marks(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            db.add(MessageTemplate(key='winback', template='Свой', enabled=False))
            await db.commit()
        callback = _callback(h.CB_ROOT)

        await _run(session_factory, h.cb_root, callback, None, _admin(admin), _state())

        buttons = _buttons(_shown(callback)[1])
        event_buttons = [b for b in buttons if b.callback_data.startswith(h.CB_CARD)]
        assert [b.callback_data[len(h.CB_CARD):] for b in event_buttons] == [e.key for e in EVENTS]
        winback = next(b for b in event_buttons if b.callback_data.endswith('winback'))
        assert '🚫' in winback.text and '✏️' in winback.text
        plain = next(b for b in event_buttons if b.callback_data.endswith('payment_success'))
        assert plain.text.startswith('✅') and '✏️' not in plain.text
        assert buttons[-1].callback_data == 'admin:root' or buttons[-1].callback_data.startswith('admin:')  # «Назад»

    asyncio.run(scenario())


def test_card_shows_trigger_variables_and_current_text(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        callback = _callback(f'{h.CB_CARD}payment_success')

        await _run(session_factory, h.cb_card, callback, None, _admin(admin), _state())

        text, markup = _shown(callback)
        assert 'Оплата прошла' in text and 'Платёж подтверждён' in text
        assert '{amount}' in text and '{description}' in text
        assert '✅ Оплата на сумму 249.00₽ прошла успешно.' in text  # предпросмотр с примерами
        labels = [b.text for b in _buttons(markup)]
        assert any('Изменить текст' in label for label in labels) and not any('Текст кнопки' in label for label in labels)
        assert any('Тест' in label for label in labels)

    asyncio.run(scenario())


def test_card_of_button_event_offers_button_editing(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        callback = _callback(f'{h.CB_CARD}winback')

        await _run(session_factory, h.cb_card, callback, None, _admin(admin), _state())

        assert any('Текст кнопки' in b.text for b in _buttons(_shown(callback)[1]))

    asyncio.run(scenario())


def test_edit_flow_saves_after_confirmation_and_shows_fresh_state(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await h.cb_edit(_callback(f'{h.CB_EDIT}payment_success'), _admin(admin), state)
        assert await state.get_state() == AdminTemplateStates.entering_text.state

        message = _message('🧾 <b>{amount}₽</b> — {description}')
        await _run(session_factory, h.on_template_text, message, None, _admin(admin), state)
        assert await state.get_state() == AdminTemplateStates.confirming.state
        assert '249.00' in message.answer.await_args.args[0]  # предпросмотр
        assert await get_overrides() == {}  # до подтверждения ничего не сохранено

        callback = _callback(h.CB_SAVE)
        async with session_factory() as db:
            await h.cb_save(callback, db, _admin(admin), state)
            # ещё ДО коммита экран уже показывает свежее состояние (читает сессию обработчика)
            assert 'текст изменён' in _shown(callback)[0]
            assert await get_overrides() == {}  # другие читатели до коммита видят старое
            await db.commit()

        assert await state.get_state() is None
        assert (await get_overrides())['payment_success'].template == '🧾 <b>{amount}₽</b> — {description}'

    asyncio.run(scenario())


def test_invalid_text_is_rejected_with_reasons_and_state_is_kept(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await h.cb_edit(_callback(f'{h.CB_EDIT}payment_success'), _admin(admin), state)

        message = _message('<b>не закрыт {nope}')
        await _run(session_factory, h.on_template_text, message, None, _admin(admin), state)

        reply = message.answer.await_args.args[0]
        assert '{nope}' in reply and 'Не закрыты' in reply
        assert await state.get_state() == AdminTemplateStates.entering_text.state
        assert await get_overrides() == {}

    asyncio.run(scenario())


def test_custom_emoji_message_is_converted_to_tg_emoji_markup(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        real = Message(
            message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=ADMIN_TG, type='private'),
            text='🏦 Подписка закончилась',
            entities=[MessageEntity(type='custom_emoji', offset=0, length=2, custom_emoji_id='5368446439800197476')],
        )
        state = _state()
        await h.cb_edit(_callback(f'{h.CB_EDIT}subscription_expired'), _admin(admin), state)
        message = _message(real.html_text)  # то, что aiogram отдаёт из настоящего сообщения
        await _run(session_factory, h.on_template_text, message, None, _admin(admin), state)
        await _run(session_factory, h.cb_save, _callback(h.CB_SAVE), None, _admin(admin), state)

        saved = (await get_overrides())['subscription_expired'].template
        assert saved == '<tg-emoji emoji-id="5368446439800197476">🏦</tg-emoji> Подписка закончилась'
        reply = message.answer.await_args.args[0]
        assert 'Тест' in reply  # предупреждение про проверку эмодзи
        assert '<tg-emoji' not in reply  # в предпросмотре — только символ

    asyncio.run(scenario())


def test_cancel_discards_pending_text(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await h.cb_edit(_callback(f'{h.CB_EDIT}subscription_expired'), _admin(admin), state)
        await _run(session_factory, h.on_template_text, _message('Новый текст'), None, _admin(admin), state)

        await _run(session_factory, h.cb_cancel, _callback(f'{h.CB_CANCEL}subscription_expired'), None, _admin(admin), state)

        assert await state.get_state() is None
        assert await get_overrides() == {}

    asyncio.run(scenario())


def test_button_text_flow(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await h.cb_button(_callback(f'{h.CB_BUTTON}winback'), _admin(admin), state)
        assert await state.get_state() == AdminTemplateStates.entering_button.state

        await _run(session_factory, h.on_button_text, _message('<b>жирная</b>'), None, _admin(admin), state)
        assert await get_overrides() == {} and await state.get_state() == AdminTemplateStates.entering_button.state

        await _run(session_factory, h.on_button_text, _message('Вернуться'), None, _admin(admin), state)
        assert (await get_overrides())['winback'].button_text == 'Вернуться' and await state.get_state() is None

        await h.cb_button(_callback(f'{h.CB_BUTTON}winback'), _admin(admin), state)
        await _run(session_factory, h.on_button_text, _message('-'), None, _admin(admin), state)  # «-» — заводская подпись
        assert (await get_overrides())['winback'].button_text is None

    asyncio.run(scenario())


def test_toggle_reset_and_test_send(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        await _run(session_factory, h.cb_toggle, _callback(f'{h.CB_TOGGLE}winback'), None, _admin(admin))
        assert (await get_overrides())['winback'].enabled is False
        await _run(session_factory, h.cb_toggle, _callback(f'{h.CB_TOGGLE}winback'), None, _admin(admin))
        assert (await get_overrides())['winback'].enabled is True

        await _run(session_factory, h.cb_reset, _callback(f'{h.CB_RESET}winback'), None, _admin(admin))
        assert await get_overrides() == {}

        callback = _callback(f'{h.CB_TEST}payment_success')
        await h.cb_test(callback, _admin(admin))
        kwargs = callback.bot.send_message.await_args.kwargs
        assert kwargs['chat_id'] == ADMIN_TG and kwargs['text'].startswith('✅ Оплата на сумму 249.00₽')

    asyncio.run(scenario())


def test_test_send_shows_telegram_rejection_as_alert(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            db.add(MessageTemplate(key='subscription_expired', template='<tg-emoji emoji-id="1">🏦</tg-emoji> x'))
            await db.commit()
        invalidate_cache()
        callback = _callback(f'{h.CB_TEST}subscription_expired')
        callback.bot.send_message.side_effect = TelegramBadRequest(
            method=SendMessage(chat_id=ADMIN_TG, text='x'), message='Bad Request: ENTITY_TEXT_INVALID'
        )

        await h.cb_test(callback, _admin(admin))

        args, kwargs = callback.answer.await_args
        assert kwargs.get('show_alert') is True and 'ENTITY_TEXT_INVALID' in args[0]

    asyncio.run(scenario())


def test_unknown_event_in_callback_is_handled(session_factory):
    async def scenario():
        admin = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        callback = _callback(f'{h.CB_CARD}no_such_event')

        await _run(session_factory, h.cb_card, callback, None, _admin(admin), _state())  # не должно бросать

        callback.answer.assert_awaited()

    asyncio.run(scenario())
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_message_templates_bot.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError: app.handlers.message_templates_admin`).

- [ ] **Step 3: Состояния**

В `app/states.py` добавьте:

```python
class AdminTemplateStates(StatesGroup):
    """Редактор автоматических сообщений: ввод текста -> подтверждение; ввод подписи кнопки."""

    entering_text = State()
    confirming = State()
    entering_button = State()
```

- [ ] **Step 4: Обработчики**

Создайте `app/handlers/message_templates_admin.py`:

```python
"""Редактор автоматических сообщений в админке бота: /admin → «✉️ Сообщения».

Текст присылается обычным сообщением: message.html_text превращает форматирование и Premium-эмодзи
(сущность custom_emoji) в HTML с <tg-emoji emoji-id="…">. Проверки и сохранение — в
app/services/message_templates (общие с веб-админкой). Экраны читают состояние из сессии обработчика,
а не из общего кэша: коммит делает AuthMiddleware ПОСЛЕ обработчика, и админ должен сразу видеть
только что сохранённое."""

from __future__ import annotations

import html
import re

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.handlers.admin import CB_ADMIN_ROOT, _answer_or_edit, _back_keyboard, _is_admin
from app.services.message_templates.registry import EVENTS, EventDef, UnknownEventError, get_event
from app.services.message_templates.service import (
    TemplateValidationError,
    build_preview,
    compose,
    load_overrides,
    reset_template,
    send_test_message,
    update_template,
)
from app.services.message_templates.validation import validate_button_text, validate_template
from app.states import AdminTemplateStates

router = Router(name='message_templates_admin')

CB_ROOT = 'tpl:root'
CB_CARD = 'tpl:card:'
CB_EDIT = 'tpl:edit:'
CB_BUTTON = 'tpl:btn:'
CB_TOGGLE = 'tpl:toggle:'
CB_RESET = 'tpl:reset:'
CB_TEST = 'tpl:test:'
CB_SAVE = 'tpl:save'
CB_CANCEL = 'tpl:cancel:'

_TG_EMOJI_RE = re.compile(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', re.S)


def _plain(text: str) -> str:
    """Для показа внутри служебных сообщений: <tg-emoji> заменяем символом (отображение не должно
    зависеть от Premium; настоящий вид проверяется кнопкой «Тест мне»)."""
    return _TG_EMOJI_RE.sub(r'\1', text)


def _key_from(data: str, prefix: str) -> str:
    return data[len(prefix):]


def _event_or_none(key: str) -> EventDef | None:
    try:
        return get_event(key)
    except UnknownEventError:
        return None


# --- экраны ------------------------------------------------------------------------------------------------


async def _root_screen(db: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    overrides = await load_overrides(db)
    rows = []
    for event in EVENTS:
        override = overrides.get(event.key)
        mark = '🚫' if override is not None and not override.enabled else '✅'
        edited = ' ✏️' if override is not None and override.template is not None else ''
        rows.append([InlineKeyboardButton(text=f'{mark} {event.title}{edited}', callback_data=f'{CB_CARD}{event.key}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data=CB_ADMIN_ROOT)])
    text = (
        '✉️ <b>Автоматические сообщения бота</b>\n\n'
        'Выберите сообщение, чтобы посмотреть и изменить его текст.\n'
        '✅ включено · 🚫 выключено · ✏️ текст изменён'
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _card_screen(event: EventDef, db: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    override = (await load_overrides(db)).get(event.key)
    rendered = compose(event, override, event.samples())
    enabled = override.enabled if override is not None else True
    customised = override is not None and override.template is not None
    variables = '\n'.join(
        f'• <code>{{{v.name}}}</code> — {html.escape(v.description)}' for v in event.variables
    ) or '• нет переменных'
    lines = [
        f'✉️ <b>{html.escape(event.title)}</b>',
        f'Когда отправляется: {html.escape(event.trigger)}',
        f'Статус: {"✅ включено" if enabled else "🚫 выключено"} · {"✏️ текст изменён" if customised else "заводской текст"}',
        '',
        'Переменные:',
        variables,
        '',
        'Как выглядит сейчас (с примерами):',
        '———',
        _plain(rendered.text),
        '———',
    ]
    if rendered.button_text:
        lines.append(f'Кнопка: «{html.escape(rendered.button_text)}»')
    keyboard = [[InlineKeyboardButton(text='✏️ Изменить текст', callback_data=f'{CB_EDIT}{event.key}')]]
    if event.has_button:
        keyboard.append([InlineKeyboardButton(text='🔘 Текст кнопки', callback_data=f'{CB_BUTTON}{event.key}')])
    keyboard.append(
        [InlineKeyboardButton(text='🔕 Выключить' if enabled else '🔔 Включить', callback_data=f'{CB_TOGGLE}{event.key}')]
    )
    keyboard.append(
        [
            InlineKeyboardButton(text='📨 Тест мне', callback_data=f'{CB_TEST}{event.key}'),
            InlineKeyboardButton(text='↩️ Сбросить', callback_data=f'{CB_RESET}{event.key}'),
        ]
    )
    keyboard.append([InlineKeyboardButton(text='⬅️ К списку', callback_data=CB_ROOT)])
    return '\n'.join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard)


def _errors_text(errors: list[str]) -> str:
    return '❌ Не удалось сохранить:\n' + '\n'.join(f'• {html.escape(error)}' for error in errors)


# --- обработчики -------------------------------------------------------------------------------------------


@router.callback_query(F.data == CB_ROOT)
async def cb_root(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    await state.clear()
    text, keyboard = await _root_screen(db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_CARD))
async def cb_card(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_CARD))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    await state.clear()
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_EDIT))
async def cb_edit(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_EDIT))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    await state.update_data(template_key=event.key)
    await state.set_state(AdminTemplateStates.entering_text)
    variables = ', '.join(f'<code>{{{name}}}</code>' for name in event.variable_names) or 'нет'
    required = (
        '\nОбязательно: ' + ', '.join('{' + name + '}' for name in event.required_variables)
        if event.required_variables
        else ''
    )
    text = (
        f'✏️ <b>{html.escape(event.title)}</b>\n\n'
        'Пришлите новый текст ОДНИМ сообщением. Можно использовать форматирование Telegram и Premium-эмодзи — '
        'бот сохранит их как есть.\n'
        f'Переменные (вставьте в текст как есть): {variables}{html.escape(required)}'
    )
    await _answer_or_edit(callback, text, _back_keyboard(f'{CB_CARD}{event.key}', '↩️ Отмена'))
    await callback.answer()


@router.message(AdminTemplateStates.entering_text, F.text)
async def on_template_text(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none((await state.get_data()).get('template_key') or '')
    if event is None:
        await state.clear()
        return
    new_html = message.html_text
    result = validate_template(event, new_html)
    if not result.ok:
        await message.answer(_errors_text(result.errors) + '\n\nПришлите исправленный текст или нажмите «Отмена».')
        return
    await state.update_data(pending_html=new_html)
    await state.set_state(AdminTemplateStates.confirming)
    preview = await build_preview(event.key, template=new_html)
    warnings = ''.join(f'\n\n⚠️ {html.escape(warning)}' for warning in result.warnings)
    await message.answer(
        f'Предпросмотр (с примерами переменных):\n———\n{_plain(preview.text)}\n———{warnings}',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text='✅ Сохранить', callback_data=CB_SAVE)],
                [InlineKeyboardButton(text='↩️ Отмена', callback_data=f'{CB_CANCEL}{event.key}')],
            ]
        ),
    )


@router.message(AdminTemplateStates.entering_text)
async def on_template_not_text(message: Message, db_user: User | None) -> None:
    if _is_admin(db_user):
        await message.answer('Пришлите текст сообщением (можно с форматированием и эмодзи).')


@router.callback_query(F.data == CB_SAVE, AdminTemplateStates.confirming)
async def cb_save(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    data = await state.get_data()
    event = _event_or_none(data.get('template_key') or '')
    pending = data.get('pending_html')
    if event is None or pending is None:
        await state.clear()
        await callback.answer('Нечего сохранять', show_alert=True)
        return
    try:
        await update_template(db, event.key, admin_user_id=db_user.id, template=pending)
    except TemplateValidationError as error:
        await callback.answer('; '.join(error.errors)[:190], show_alert=True)
        return
    await state.clear()
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, '✅ Сохранено\n\n' + text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_CANCEL))
async def cb_cancel(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    await state.clear()
    event = _event_or_none(_key_from(callback.data, CB_CANCEL))
    if event is None:
        await callback.answer()
        return
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer('Отменено')


@router.callback_query(F.data.startswith(CB_BUTTON))
async def cb_button(callback: CallbackQuery, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_BUTTON))
    if event is None or not event.has_button:
        await callback.answer('У этого сообщения нет кнопки', show_alert=True)
        return
    await state.update_data(template_key=event.key)
    await state.set_state(AdminTemplateStates.entering_button)
    await _answer_or_edit(
        callback,
        '🔘 Пришлите новую подпись кнопки (до 64 символов, без форматирования и без кастомных эмодзи).\n'
        f'Символ «-» вернёт заводскую подпись: «{html.escape(event.button_label(True) or "")}».',
        _back_keyboard(f'{CB_CARD}{event.key}', '↩️ Отмена'),
    )
    await callback.answer()


@router.message(AdminTemplateStates.entering_button, F.text)
async def on_button_text(message: Message, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none((await state.get_data()).get('template_key') or '')
    if event is None:
        await state.clear()
        return
    label = (message.text or '').strip()
    value: str | None = None if label == '-' else label
    errors = validate_button_text(event, value) if value is not None else []
    if errors:
        await message.answer(_errors_text(errors) + '\n\nПришлите другую подпись или нажмите «Отмена».')
        return
    await update_template(db, event.key, admin_user_id=db_user.id, button_text=value)
    await state.clear()
    text, keyboard = await _card_screen(event, db)
    await message.answer('✅ Сохранено\n\n' + text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(CB_TOGGLE))
async def cb_toggle(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_TOGGLE))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    override = (await load_overrides(db)).get(event.key)
    currently_enabled = override.enabled if override is not None else True
    await update_template(db, event.key, admin_user_id=db_user.id, enabled=not currently_enabled)
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer('Включено' if not currently_enabled else 'Выключено')


@router.callback_query(F.data.startswith(CB_RESET))
async def cb_reset(callback: CallbackQuery, db: AsyncSession, db_user: User | None) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_RESET))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    await reset_template(db, event.key, admin_user_id=db_user.id)
    text, keyboard = await _card_screen(event, db)
    await _answer_or_edit(callback, text, keyboard)
    await callback.answer('Сброшено к заводскому')


@router.callback_query(F.data.startswith(CB_TEST))
async def cb_test(callback: CallbackQuery, db_user: User | None) -> None:
    if not _is_admin(db_user):
        return
    event = _event_or_none(_key_from(callback.data, CB_TEST))
    if event is None:
        await callback.answer('Такого сообщения нет', show_alert=True)
        return
    try:
        await send_test_message(callback.bot, telegram_id=callback.from_user.id, key=event.key)
    except TelegramBadRequest as error:
        await callback.answer(f'Telegram отклонил сообщение: {error.message}'[:190], show_alert=True)
        return
    except Exception:
        await callback.answer('Не удалось отправить тестовое сообщение', show_alert=True)
        return
    await callback.answer('📨 Отправлено вам в чат')


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
```

- [ ] **Step 5: Подключить редактор**

`app/handlers/admin.py`, в `_root_keyboard` добавьте строку кнопки после ряда «Статистика / Рассылка» (`apply_patch`):

```python
# OLD
            [
                InlineKeyboardButton(text='📊 Статистика', callback_data=CB_STATS_MENU),
                InlineKeyboardButton(text='📢 Рассылка', callback_data=CB_ADMIN_BROADCAST),
            ],
# NEW
            [
                InlineKeyboardButton(text='📊 Статистика', callback_data=CB_STATS_MENU),
                InlineKeyboardButton(text='📢 Рассылка', callback_data=CB_ADMIN_BROADCAST),
            ],
            [InlineKeyboardButton(text='✉️ Сообщения', callback_data='tpl:root')],
```

`app/handlers/__init__.py`, перед регистрацией `admin` (`apply_patch`):

```python
# OLD
    from app.handlers import admin

    admin.register_handlers(dp)
# NEW
    from app.handlers import message_templates_admin

    message_templates_admin.register_handlers(dp)

    from app.handlers import admin

    admin.register_handlers(dp)
```

- [ ] **Step 6: Тесты проходят**

Run: `python -m pytest tests/test_message_templates_bot.py -q -p no:warnings` → PASS; затем весь набор.
Если `_shown(callback)` не находит вызов — обработчик показал экран через `callback.message.answer` после неудачного `edit_text`; в фейке `edit_text` — `AsyncMock`, который не падает, поэтому `_answer_or_edit` использует `edit_text`.

- [ ] **Step 7: Мутации**

По одной, каждая роняет тест, затем откат: в `on_template_text` убрать проверку `if not result.ok` (упадёт тест невалидного текста); в `_card_screen` заменить `_plain(rendered.text)` на `rendered.text` (упадёт проверка `<tg-emoji` в предпросмотре); в `cb_toggle` убрать `not` перед `currently_enabled`; в `_card_screen` заменить `load_overrides(db)` на `get_overrides()` (упадёт проверка «свежее состояние до коммита» в `test_edit_flow…`).

- [ ] **Step 8: Коммит**

```bash
git add app/handlers/message_templates_admin.py app/handlers/admin.py app/handlers/__init__.py app/states.py tests/test_message_templates_bot.py
git commit -m "Добавляет редактор автоматических сообщений в админке бота"
```

---

### Task 9: Документация API и финальная проверка

**Files:**
- Modify: `scripts/generate_api_docs.py`, `docs/api/API.md`, перегенерировать `docs/api/*`

- [ ] **Step 1: Описания и группа в генераторе**

В `scripts/generate_api_docs.py` добавьте в блок ручных описаний (после админских эндпоинтов, вызовы `add(...)`):

```python
# --- админка: уведомления бота
add('GET', '/cabinet/admin/notifications/templates', 'Автоматические сообщения бота', 'Все 15 событий с текущим текстом, заводским текстом, переменными, признаками `is_customized`/`enabled`, подписью кнопки (если есть) и автором последней правки.')
add('PUT', '/cabinet/admin/notifications/templates/{key}', 'Изменить сообщение', 'Частичное обновление: применяются только переданные поля. `template` — текст в HTML Telegram (разрешённые теги, переменные `{имя}` из списка события; кастомные эмодзи — `<tg-emoji emoji-id="…">`); `template: null` возвращает заводской текст; `enabled: false` отключает отправку; `button_text` — подпись кнопки (у событий с кнопкой). Изменения действуют сразу. Ошибки проверок — `422` со списком сообщений.')
add('DELETE', '/cabinet/admin/notifications/templates/{key}', 'Сбросить сообщение к заводскому', 'Удаляет правку целиком (текст, кнопку, флаг «включено»). Повторный вызов безопасен.')
add('POST', '/cabinet/admin/notifications/templates/{key}/preview', 'Предпросмотр', 'Рендерит текст с примерами переменных без сохранения; возвращает длину видимого текста и предупреждения (например, про кастомные эмодзи). Пустое тело — предпросмотр текущего текста.')
add('POST', '/cabinet/admin/notifications/templates/{key}/test', 'Отправить тест мне', 'Отправляет предпросмотр вызвавшему админу в Telegram (с настоящей кнопкой, если она есть). `502` с текстом причины, если Telegram отклонил сообщение (например, недопустимое кастомное эмодзи).')
add('GET', '/cabinet/admin/notifications/emoji', 'Кастомные эмодзи', 'Кастомные эмодзи из `app/emoji.py` с заданным ID — для вставки в текст.')
```

и в список `GROUPS_ADMIN` новую группу:

```python
    ('Уведомления бота', ['/cabinet/admin/notifications/templates', '/cabinet/admin/notifications/templates/{key}', '/cabinet/admin/notifications/templates/{key}/preview', '/cabinet/admin/notifications/templates/{key}/test', '/cabinet/admin/notifications/emoji']),
```

- [ ] **Step 2: Перегенерировать**

Run (PowerShell): `$env:BOT_TOKEN='x'; python scripts/generate_api_docs.py`
Expected: `missing from groups: []` и `summaries missing: []`; в `docs/api/reference-admin.md` появился раздел «Уведомления бота» (6 операций), в `schemas.md` — `TemplateOut`, `TemplateUpdateRequest`, `PreviewRequest`, `PreviewResponse`, `EmojiOut`, `VariableDocOut`.

- [ ] **Step 3: Раздел в `API.md`**

В `docs/api/API.md` перед разделом «Что изменится (план центра аналитики)» добавьте:

```markdown
## Шаблоны автоматических сообщений

Бот сам отправляет 15 видов сообщений (оплата, истечение подписки, бонусы, автоплатёж, напоминания). Их тексты можно менять из админки — эндпоинты `/cabinet/admin/notifications/*` ([справочник](reference-admin.md#уведомления-бота)) — и из бота (`/admin` → «✉️ Сообщения»).

- Заводские тексты лежат в коде и всегда доступны; правки хранятся в БД и действуют **сразу** (кэш до 60 секунд, сбрасывается при сохранении).
- Текст — HTML Telegram; разрешены теги `b, strong, i, em, u, ins, s, strike, del, a, code, pre, tg-spoiler, blockquote, tg-emoji`. Подстановки `{имя}` — только из списка переменных события; значения экранируются.
- Кастомные эмодзи — `<tg-emoji emoji-id="…">символ</tg-emoji>` (символ обязан совпадать с «родным» символом эмодзи). Работают только если у владельца бота Telegram Premium; список известных ID — `GET /emoji`. В подписи кнопки эмодзи-кастомы запрещены.
- Событие можно выключить (`enabled: false`): сообщение не отправляется.
- Если Telegram отклонил сообщение из-за разметки или эмодзи, пользователь получает **заводской текст**, а в логе появляется `template_fallback`.
```

- [ ] **Step 4: Полная проверка**

Run: `python -m pytest tests -q -p no:warnings` → PASS (199 прежних + новые).
Run: `python -c "import os;os.environ['BOT_TOKEN']='1:t'; import main; import app.cabinet.app; print('import ok')"` → `import ok`.
Run: `grep -rn "_safe_send\|_renew_button" app --include=*.py` → только упоминание в комментарии `background.py`.
Проверка ссылок документации: убедитесь, что якорь `#уведомления-бота` существует в `reference-admin.md` (заголовок `## Уведомления бота`).

- [ ] **Step 5: Ручная проверка владельцем (после деплоя)**

1. Применить миграцию (при старте контейнера выполняется `alembic upgrade head`).
2. В боте: `/admin` → «✉️ Сообщения» → «Подписка истекла» → «✏️ Изменить текст» → прислать текст с Premium-эмодзи → «Сохранить» → «📨 Тест мне» (сообщение приходит вам; при отказе Telegram видно причину).
3. Убедиться, что до правок бот шлёт прежние тексты (например, вызвать «Тест мне» у любого события — текст совпадает с заводским).
4. Выключить событие «Возвращение клиента» и проверить, что рассылка `winback` больше не уходит; включить обратно; «↩️ Сбросить» возвращает заводской текст.

- [ ] **Step 6: Коммит**

```bash
git add scripts/generate_api_docs.py docs/api
git commit -m "Документирует API шаблонов сообщений и перегенерирует справочник"
```

---

## Покрытие спецификации

| Раздел спецификации | Задача |
|---|---|
| §4 реестр событий, заводские тексты дословно | 2, 1 (характеризация), 6 (золотая проверка) |
| §5 таблица `message_templates` | 4 |
| §6 отправка: кэш, выключение, откат, `notify_*` не меняются | 5, 6 |
| §7 проверки при сохранении | 3 |
| §8 API | 7 |
| §9 редактор в боте | 8 |
| §10 тестирование (золотые, рендер, проверки, API, бот, мутации) | 1, 3, 5, 6, 7, 8 |
| §11 ошибки и защита, логи | 5 (`template_fallback`, `template_updated`, `template_reset`, `notification_skipped`) |
| §12 выкладка и документация | 9 |

**Не входят в этот план:** страница «Уведомления» во фронтенде (NRW-MiniApp, по контракту `docs/api/`), многоязычность, тексты приветствия/меню/обработчиков, условия и время отправки, история версий.
