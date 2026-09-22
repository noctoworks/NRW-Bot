# API рассылок для веб-админки — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** дать веб-админке возможность запускать рассылки по пользователям через API
(`/cabinet/admin/broadcasts/*`), не дублируя логику отправки, которая сейчас живёт только
в боте (`app/handlers/admin.py`).

**Architecture:** общий сервис `app/services/broadcast_service.py` — единственное место с
логикой аудиторий, кнопок-конструктора, батчей/ретраев и прогресса. Бот вызывает его
СИНХРОННО (ждёт завершения — как сейчас), API — АСИНХРОННО (запускает фоновую задачу,
отвечает сразу, прогресс — через `GET`). Обе точки входа используют общую подготовку
(`_prepare_broadcast`) и общий цикл отправки (`_run`), поэтому «одна рассылка одновременно»
и отмена работают одинаково независимо от того, кто её запустил.

**Tech Stack:** Python 3.14, aiogram 3, FastAPI, SQLAlchemy 2 async, pytest (`asyncio.run`,
без pytest-asyncio), SQLite в тестах / Postgres в проде.

**Spec:** `docs/superpowers/specs/2026-09-22-broadcast-api-design.md`

## Global Constraints

- Единственная реализация отправки — `app/services/broadcast_service.py`. `app/handlers/admin.py`
  и `app/cabinet/broadcast_routes.py` не содержат собственной логики батчей/ретраев/аудиторий.
- Не более одной рассылки одновременно (проверка — по `BroadcastHistory.status == 'in_progress'`,
  единая для бота и API).
- Прогресс коммитится в БД периодически (каждые `PROGRESS_COMMIT_INTERVAL = 5.0` сек, как раньше
  редактировалось сообщение бота), не только в конце.
- Отмена — через `asyncio.Event` в памяти процесса (`_cancel_flags`), проверяется перед каждой
  пачкой; уже отправленные сообщения не откатываются.
- Медиа — только `file_id`, полученный где-то ещё. Загрузка файла через API не входит в эту версию.
- При старте процесса все `BroadcastHistory.status == 'in_progress'` помечаются `interrupted`
  (ничего не возобновляется).
- `tests/test_broadcast_golden.py` (Task 1) фиксирует поведение БОТА (тексты, клавиатуры,
  содержимое `BroadcastHistory`) и не редактируется в Tasks 2 и 4 — рефакторинг синхронного пути
  бота не меняет наблюдаемое поведение (см. Architecture: бот использует `run_broadcast_now`,
  которое ждёт завершения так же, как старый инлайн-цикл).
- Коммиты — русские сообщения, трейлер `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Полный набор тестов (386 на момент написания плана) должен проходить после каждой задачи.

---

### Task 1: Характеризационные тесты рассылки в боте (до рефакторинга)

**Files:**
- Create: `tests/test_broadcast_golden.py`

**Interfaces:**
- Consumes: текущие (нерефакторенные) `app/handlers/admin.py` — `cb_admin_broadcast`,
  `cb_broadcast_target_tariff_menu`, `cb_broadcast_pick_target`, `on_admin_broadcast_text`,
  `cb_broadcast_media_pick`, `on_admin_broadcast_media`, `cb_broadcast_media_confirm`,
  `cb_broadcast_btn_toggle`, `cb_broadcast_btn_continue`, `cb_admin_broadcast_confirm`,
  `cb_broadcast_history`, `AdminBroadcastStates`, `BROADCAST_TARGETS`, `BROADCAST_BUTTONS`,
  `DEFAULT_BROADCAST_BUTTONS`.
- Produces: зафиксированное поведение, которое Tasks 2 и 4 обязаны сохранить.

- [ ] **Step 1: Написать тесты**

Создайте `tests/test_broadcast_golden.py`:

```python
"""Рассылка в боте — характеризация ДО выноса логики отправки в сервис
(docs/superpowers/plans/2026-09-22-broadcast-api.md). Тексты экранов, клавиатуры и содержимое
BroadcastHistory зафиксированы построчно; после Tasks 2 и 4 этот файл НЕ редактируется — бот
переходит на broadcast_service.run_broadcast_now, которое ждёт отправку целиком так же, как
прежний инлайн-цикл, поэтому наблюдаемое поведение не меняется."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage

from app.database.models import BroadcastHistory, Subscription, User
from app.handlers import admin as h
from app.states import AdminBroadcastStates
from tests.helpers import make_tariff, make_user

ADMIN_TG = 555


def _state() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=ADMIN_TG, user_id=ADMIN_TG))


def _admin(admin_id: int) -> User:
    return User(id=admin_id, telegram_id=ADMIN_TG, referral_code='a', is_admin=True)


def _callback(data: str, bot=None):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=ADMIN_TG),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock(), answer_photo=AsyncMock()),
        answer=AsyncMock(),
        bot=bot if bot is not None else AsyncMock(),
    )


def _message(text: str):
    return SimpleNamespace(text=text, answer=AsyncMock())


def _shown(callback) -> tuple[str, object]:
    """(текст, клавиатура) ПОСЛЕДНЕГО показанного экрана (edit_text либо answer)."""
    for method in (callback.message.edit_text, callback.message.answer):
        if method.await_args is not None:
            args, kwargs = method.await_args
            return args[0], kwargs.get('reply_markup')
    raise AssertionError('экран не показан')


def _buttons(markup) -> list:
    return [button for row in markup.inline_keyboard for button in row]


async def _add_subscription(factory, user_id: int, tariff_id: int, *, status: str, days_left: int) -> None:
    async with factory() as db:
        db.add(Subscription(
            user_id=user_id, tariff_id=tariff_id, status=status,
            end_date=datetime.now(timezone.utc) + timedelta(days=days_left),
        ))
        await db.commit()


def test_audience_screen_lists_categories_and_history_button(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            callback = _callback(h.CB_ADMIN_BROADCAST)
            state = _state()
            await h.cb_admin_broadcast(callback, _admin(admin_id), state)
            text, markup = _shown(callback)
            assert text == '🎯 <b>Выбор целевой аудитории</b>\n\nВыберите категорию пользователей для рассылки:'
            labels = [b.text for b in _buttons(markup)]
            assert labels == ['👥 Всем', '📱 С подпиской', '❌ Без подписки', '⏰ Истекающие', '🔚 Истёкшие',
                               '📦 По тарифу', '📋 История рассылок', '⬅️ Назад']
            assert (await state.get_state()) == AdminBroadcastStates.choosing_target.state

    asyncio.run(scenario())


def test_pick_target_shows_count_and_prompts_for_text(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        tariff_id = await make_tariff(session_factory)
        await make_user(session_factory, telegram_id=1)
        active_id = await make_user(session_factory, telegram_id=2)
        await _add_subscription(session_factory, active_id, tariff_id, status='active', days_left=10)

        async with session_factory() as db:
            callback = _callback(f'{h.CB_BROADCAST_TARGET}active')
            state = _state()
            await h.cb_broadcast_pick_target(callback, db, _admin(admin_id), state)
            text, markup = _shown(callback)
            assert text == (
                '📨 <b>Создание рассылки</b>\n\n🎯 <b>Аудитория:</b> 📱 С подпиской\n👥 <b>Получателей:</b> 1\n\n'
                'Введите текст сообщения (поддерживается HTML, до 4000 символов):'
            )
            assert (await state.get_state()) == AdminBroadcastStates.entering_text.state
            assert (await state.get_data())['broadcast_target'] == 'active'

    asyncio.run(scenario())


def test_text_over_4000_chars_is_rejected():
    async def scenario():
        message = _message('x' * 4001)
        await h.on_admin_broadcast_text(message, _admin(1), _state())
        message.answer.assert_awaited_once_with('❌ Сообщение слишком длинное (максимум 4000 символов)')

    asyncio.run(scenario())


async def _to_button_selector(state: FSMContext) -> SimpleNamespace:
    """Аудитория 'all' → текст → пропуск медиа → экран выбора кнопок. Возвращает callback последнего шага."""
    await state.update_data(broadcast_target='all', broadcast_text='Привет!')
    await state.set_state(AdminBroadcastStates.choosing_media)
    callback = _callback(f'{h.CB_BROADCAST_MEDIA}skip')
    await h.cb_broadcast_media_pick(callback, _admin(1), state)
    return callback


def test_skip_media_shows_button_selector_with_home_checked_by_default():
    async def scenario():
        state = _state()
        callback = await _to_button_selector(state)
        text, markup = _shown(callback)
        assert text.startswith('📘 <b>Выбор дополнительных кнопок</b>')
        marks = {b.text[0]: b.text for row in markup.inline_keyboard for b in row}
        home_button = next(b for row in markup.inline_keyboard for b in row if 'На главную' in b.text)
        assert home_button.text.startswith('✅')
        subscription_button = next(b for row in markup.inline_keyboard for b in row if 'Моя подписка' in b.text)
        assert subscription_button.text.startswith('⬜')
        assert (await state.get_state()) == AdminBroadcastStates.choosing_buttons.state

    asyncio.run(scenario())


def test_toggle_button_flips_the_checkmark():
    async def scenario():
        state = _state()
        await _to_button_selector(state)
        callback = _callback(f'{h.CB_BROADCAST_BTN_TOGGLE}referrals')
        await h.cb_broadcast_btn_toggle(callback, _admin(1), state)
        markup = callback.message.edit_reply_markup.await_args.kwargs['reply_markup']
        referrals_button = next(b for row in markup.inline_keyboard for b in row if 'Партнёрка' in b.text)
        assert referrals_button.text.startswith('✅')
        assert 'referrals' in (await state.get_data())['selected_buttons']

    asyncio.run(scenario())


def test_continue_shows_preview_with_audience_text_and_buttons(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        state = _state()
        await state.update_data(broadcast_target='all', broadcast_text='Привет всем!', selected_buttons=['home'])
        async with session_factory() as db:
            callback = _callback(h.CB_BROADCAST_BTN_CONTINUE)
            await h.cb_broadcast_btn_continue(callback, db, _admin(admin_id), state)
            text, markup = _shown(callback)
            assert '📨 <b>Предварительный просмотр рассылки</b>' in text
            assert '🎯 <b>Аудитория:</b> 👥 Всем' in text
            assert '📝 <b>Сообщение:</b>\nПривет всем!' in text
            assert '📘 <b>Кнопки:</b> 🏠 На главную' in text
            assert [b.text for b in _buttons(markup)] == ['✅ Отправить', '❌ Отмена']
            assert (await state.get_state()) == AdminBroadcastStates.confirming.state

    asyncio.run(scenario())


def test_confirm_sends_to_all_recipients_and_records_mixed_result(session_factory):
    """2 получателя: одному письмо доходит, второй заблокировал бота — итог 'partial'."""

    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        ok_id = await make_user(session_factory, telegram_id=101)
        blocked_id = await make_user(session_factory, telegram_id=102)

        bot = AsyncMock()
        bot.send_message.side_effect = [SimpleNamespace(message_id=1), TelegramForbiddenError(
            method=SendMessage(chat_id=102, text='x'), message='bot blocked'
        )]

        state = _state()
        await state.update_data(broadcast_target='all', broadcast_text='Привет!', selected_buttons=['home'])
        async with session_factory() as db:
            callback = _callback(h.CB_BROADCAST_CONFIRM, bot=bot)
            await h.cb_admin_broadcast_confirm(callback, db, _admin(admin_id), state)

            callback.answer.assert_any_await('Рассылка запущена…')
            text, markup = _shown(callback)
            assert text == (
                '✅ <b>Рассылка завершена!</b>\n\n📊 Отправлено: 1\n'
                '🚫 Заблокировали бота: 1\n❌ Не доставлено: 0\n'
                '👥 Всего: 2\n📈 Успешность: 50.0%'
            )

            history = (await db.execute(
                __import__('sqlalchemy').select(BroadcastHistory)
            )).scalars().one()
            assert history.status == 'partial'
            assert history.sent_count == 1
            assert history.blocked_count == 1
            assert history.failed_count == 0
            assert history.total_count == 2
            assert history.target_type == 'all'
            assert history.message_text == 'Привет!'
            assert history.admin_id == admin_id

            blocked_user = await db.get(User, blocked_id)
            ok_user = await db.get(User, ok_id)
            assert blocked_user.blocked_bot is True
            assert ok_user.blocked_bot is False

    asyncio.run(scenario())


def test_confirm_with_photo_sends_caption_when_short(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        await make_user(session_factory, telegram_id=201)

        bot = AsyncMock()
        state = _state()
        await state.update_data(
            broadcast_target='all', broadcast_text='Фото!', selected_buttons=['home'],
            has_media=True, media_type='photo', media_file_id='FILE1',
        )
        async with session_factory() as db:
            callback = _callback(h.CB_BROADCAST_CONFIRM, bot=bot)
            await h.cb_admin_broadcast_confirm(callback, db, _admin(admin_id), state)

        bot.send_photo.assert_awaited_once()
        _, kwargs = bot.send_photo.await_args
        assert kwargs['photo'] == 'FILE1'
        assert kwargs['caption'] == 'Фото!'
        bot.send_message.assert_not_awaited()

    asyncio.run(scenario())


def test_confirm_retries_once_on_flood_control(session_factory, monkeypatch):
    monkeypatch.setattr(h.asyncio, 'sleep', AsyncMock())

    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        await make_user(session_factory, telegram_id=301)

        bot = AsyncMock()
        bot.send_message.side_effect = [
            TelegramRetryAfter(method=SendMessage(chat_id=301, text='x'), message='flood', retry_after=1),
            SimpleNamespace(message_id=2),
        ]
        state = _state()
        await state.update_data(broadcast_target='all', broadcast_text='Ретрай', selected_buttons=['home'])
        async with session_factory() as db:
            callback = _callback(h.CB_BROADCAST_CONFIRM, bot=bot)
            await h.cb_admin_broadcast_confirm(callback, db, _admin(admin_id), state)
            text, _ = _shown(callback)
            assert '📊 Отправлено: 1' in text
            assert bot.send_message.await_count == 2

    asyncio.run(scenario())


def test_history_screen_lists_completed_broadcast(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=ADMIN_TG, is_admin=True)
        async with session_factory() as db:
            db.add(BroadcastHistory(
                target_type='all', message_text='Тестовая рассылка', total_count=5, sent_count=5,
                status='completed', admin_id=admin_id, admin_name='boss',
            ))
            await db.commit()
            callback = _callback(f'{h.CB_BROADCAST_HISTORY}0')
            await h.cb_broadcast_history(callback, db, _admin(admin_id))
            text, markup = _shown(callback)
            assert '📋 <b>История рассылок</b> (стр. 1/1)' in text
            assert '✅' in text and '5/5 доставлено' in text and 'Тестовая рассылка' in text

    asyncio.run(scenario())
```

- [ ] **Step 2: Запустить тесты**

Run: `python -m pytest tests/test_broadcast_golden.py -q -p no:warnings`
Expected: 9 passed (против ТЕКУЩЕГО, нерефакторенного `admin.py`).

- [ ] **Step 3: Прогнать весь набор**

Run: `python -m pytest tests -q -p no:warnings`
Expected: 395 passed (386 + 9 новых).

- [ ] **Step 4: Коммит**

```bash
git add tests/test_broadcast_golden.py
git commit -m "Добавляет характеризационные тесты рассылки бота перед рефакторингом"
```

---

### Task 2: Сервис аудиторий/кнопок — `broadcast_service.py`, `admin.py` импортирует его

**Files:**
- Create: `app/services/broadcast_service.py`
- Modify: `app/handlers/admin.py`

**Interfaces:**
- Consumes: ничего нового (чистый перенос кода из `admin.py`).
- Produces: `BROADCAST_TARGETS`, `BROADCAST_BUTTONS`, `BROADCAST_BUTTON_ROWS`,
  `DEFAULT_BROADCAST_BUTTONS`, `ALLOWED_MEDIA_TYPES`, `async target_users(db, target) -> list[User]`,
  `async target_display_name(db, target) -> str`, `result_keyboard(selected: list[str]) ->
  InlineKeyboardMarkup | None` — использует Task 3 (продолжение этого файла) и Task 5 (API).

Никакого поведенческого изменения: golden-тесты Task 1 должны пройти БЕЗ РЕДАКТИРОВАНИЯ.

- [ ] **Step 1: Создать `app/services/broadcast_service.py`**

```python
"""Рассылка по пользователям: аудитории и кнопки-конструктор. Общий код для бота
(app/handlers/admin.py) и веб-админки (app/cabinet/broadcast_routes.py) — единственное место,
где живут категории аудитории и набор кнопок, без дублирования."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Subscription, Tariff, User
from app.handlers.promocode import CB_PROMO_ENTER
from app.keyboards.main_menu import CB_MENU_MAIN, CB_REFERRAL_MENU, CB_SUBSCRIPTION_MY, CB_SUBSCRIPTION_RENEW, CB_SUPPORT_MENU

BROADCAST_TARGETS: dict[str, str] = {
    'all': '👥 Всем',
    'active': '📱 С подпиской',
    'no_sub': '❌ Без подписки',
    'expiring': '⏰ Истекающие',
    'expired': '🔚 Истёкшие',
}

# Кнопки-конструктор для тела рассылки — используют РЕАЛЬНЫЕ callback_data других модулей
# (main_menu.py/referral.py/promocode.py/support.py): при клике по кнопке в разосланном
# сообщении сработает штатный хендлер соответствующего модуля, это не заглушки.
BROADCAST_BUTTONS: dict[str, dict[str, str]] = {
    'subscription': {'text': '📱 Моя подписка', 'callback': CB_SUBSCRIPTION_MY},
    'renew': {'text': '💎 Продлить подписку', 'callback': CB_SUBSCRIPTION_RENEW},
    'referrals': {'text': '🤝 Партнёрка', 'callback': CB_REFERRAL_MENU},
    'promocode': {'text': '🎫 Промокод', 'callback': CB_PROMO_ENTER},
    'support': {'text': '🛠️ Техподдержка', 'callback': CB_SUPPORT_MENU},
    'home': {'text': '🏠 На главную', 'callback': CB_MENU_MAIN},
}
BROADCAST_BUTTON_ROWS: tuple[tuple[str, ...], ...] = (
    ('subscription', 'renew'),
    ('referrals', 'promocode'),
    ('support',),
    ('home',),
)
DEFAULT_BROADCAST_BUTTONS: tuple[str, ...] = ('home',)

ALLOWED_MEDIA_TYPES = frozenset({'photo', 'video', 'document'})


async def target_users(db: AsyncSession, target: str) -> list[User]:
    """Единая функция и для счётчика (len(...)), и для реальной выборки — то же решение, что
    было в handlers/admin.py, перенесено без изменения поведения (неизвестный target — []).
    now, timedelta, timezone: даты хранятся в UTC (see также app/services/time_utils.py)."""
    now = datetime.now(timezone.utc)

    if target == 'all':
        stmt = select(User)
    elif target == 'active':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(Subscription.status == 'active')
    elif target == 'no_sub':
        has_active = (
            select(Subscription.id)
            .where(Subscription.user_id == User.id, Subscription.status == 'active')
            .correlate(User)
            .exists()
        )
        stmt = select(User).where(~has_active)
    elif target == 'expiring':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(
            Subscription.status == 'active',
            Subscription.end_date <= now + timedelta(days=3),
            Subscription.end_date > now,
        )
    elif target == 'expired':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(Subscription.status == 'expired')
    elif target.startswith('tariff:'):
        tariff_id = int(target.split(':', 1)[1])
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(
            Subscription.status == 'active', Subscription.tariff_id == tariff_id
        )
    else:
        return []

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def target_display_name(db: AsyncSession, target: str) -> str:
    if target in BROADCAST_TARGETS:
        return BROADCAST_TARGETS[target]
    if target.startswith('tariff:'):
        tariff = await db.get(Tariff, int(target.split(':', 1)[1]))
        return f'Тариф «{tariff.name}»' if tariff else 'Тариф (удалён)'
    return target


def result_keyboard(selected: list[str]) -> InlineKeyboardMarkup | None:
    ordered_keys = [k for row in BROADCAST_BUTTON_ROWS for k in row if k in selected]
    if not ordered_keys:
        return None
    rows = [[InlineKeyboardButton(text=BROADCAST_BUTTONS[k]['text'], callback_data=BROADCAST_BUTTONS[k]['callback'])] for k in ordered_keys]
    return InlineKeyboardMarkup(inline_keyboard=rows)
```

- [ ] **Step 2: `admin.py` — добавить импорт сразу после `from app.states import ...`**

Найдите (последняя строка блока импортов):

```python
from app.states import AdminBroadcastStates, AdminEmojiStates, AdminPromoCodeStates, AdminTariffStates, AdminUserStates
```

Замените на:

```python
from app.services import broadcast_service
from app.services.broadcast_service import (
    BROADCAST_BUTTON_ROWS,
    BROADCAST_BUTTONS,
    BROADCAST_TARGETS,
    DEFAULT_BROADCAST_BUTTONS,
)
from app.services.broadcast_service import result_keyboard as _broadcast_result_keyboard
from app.services.broadcast_service import target_display_name as _broadcast_target_display_name
from app.services.broadcast_service import target_users as _broadcast_target_users
from app.states import AdminBroadcastStates, AdminEmojiStates, AdminPromoCodeStates, AdminTariffStates, AdminUserStates
```

(Алиасы `_broadcast_*` держат ВСЕ существующие вызовы в файле рабочими без единой правки —
единственная цель этого шага — переиспользовать логику, не трогая контракт.)

- [ ] **Step 3: `admin.py` — удалить дублированные константы**

Найдите блок (между `_broadcast_target_keyboard` объявлять НЕ трогаем — только то, что ниже):

```python
BROADCAST_TARGETS: dict[str, str] = {
    'all': '👥 Всем',
    'active': '📱 С подпиской',
    'no_sub': '❌ Без подписки',
    'expiring': '⏰ Истекающие',
    'expired': '🔚 Истёкшие',
}

CB_BROADCAST_TARGET = 'broadcast:target:'  # + ключ из BROADCAST_TARGETS, либо tariff:<id>
CB_BROADCAST_TARGET_TARIFF_MENU = 'broadcast:target_tariff_menu'

CB_BROADCAST_MEDIA = 'broadcast:media:'  # + photo|video|document|skip
CB_BROADCAST_MEDIA_CONFIRM = 'broadcast:media_confirm'
CB_BROADCAST_MEDIA_CHANGE = 'broadcast:media_change'

CB_BROADCAST_BTN_TOGGLE = 'broadcast:btn:'  # + ключ кнопки
CB_BROADCAST_BTN_CONTINUE = 'broadcast:btn_continue'

CB_BROADCAST_HISTORY = 'broadcast:history:'  # + page

# Кнопки-конструктор для тела рассылки — используют РЕАЛЬНЫЕ callback_data других
# модулей (main_menu.py/referral.py/promocode.py/support.py): при клике по кнопке
# в разосланном сообщении сработает штатный хендлер соответствующего модуля,
# это не заглушки. 'balance'/'connect' у оригинала — не переносим, см. комментарий выше.
BROADCAST_BUTTONS: dict[str, dict[str, str]] = {
    'subscription': {'text': '📱 Моя подписка', 'callback': CB_SUBSCRIPTION_MY},
    'renew': {'text': '💎 Продлить подписку', 'callback': CB_SUBSCRIPTION_RENEW},
    'referrals': {'text': '🤝 Партнёрка', 'callback': CB_REFERRAL_MENU},
    'promocode': {'text': '🎫 Промокод', 'callback': CB_PROMO_ENTER},
    'support': {'text': '🛠️ Техподдержка', 'callback': CB_SUPPORT_MENU},
    'home': {'text': '🏠 На главную', 'callback': CB_MENU_MAIN},
}
BROADCAST_BUTTON_ROWS: tuple[tuple[str, ...], ...] = (
    ('subscription', 'renew'),
    ('referrals', 'promocode'),
    ('support',),
    ('home',),
)
DEFAULT_BROADCAST_BUTTONS = ('home',)

_BROADCAST_MEDIA_LABELS = {'photo': 'Фотография', 'video': 'Видео', 'document': 'Документ'}
```

Замените на (константы аудиторий/кнопок теперь в `broadcast_service`; `CB_*` и подписи медиа
остаются — это UI бота, не логика отправки):

```python
CB_BROADCAST_TARGET = 'broadcast:target:'  # + ключ из broadcast_service.BROADCAST_TARGETS, либо tariff:<id>
CB_BROADCAST_TARGET_TARIFF_MENU = 'broadcast:target_tariff_menu'

CB_BROADCAST_MEDIA = 'broadcast:media:'  # + photo|video|document|skip
CB_BROADCAST_MEDIA_CONFIRM = 'broadcast:media_confirm'
CB_BROADCAST_MEDIA_CHANGE = 'broadcast:media_change'

CB_BROADCAST_BTN_TOGGLE = 'broadcast:btn:'  # + ключ кнопки
CB_BROADCAST_BTN_CONTINUE = 'broadcast:btn_continue'

CB_BROADCAST_HISTORY = 'broadcast:history:'  # + page

_BROADCAST_MEDIA_LABELS = {'photo': 'Фотография', 'video': 'Видео', 'document': 'Документ'}
```

- [ ] **Step 4: `admin.py` — удалить перенесённые функции**

Найдите блок (от `async def _broadcast_target_users` до строки перед `def _broadcast_target_keyboard`):

```python
async def _broadcast_target_users(db: AsyncSession, target: str) -> list[User]:
    """Единая функция и для счётчика (len(...)), и для реальной выборки —
    см. комментарий в начале секции про то, почему это осознанно не два запроса."""
    now = datetime.now(timezone.utc)

    if target == 'all':
        stmt = select(User)
    elif target == 'active':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(Subscription.status == 'active')
    elif target == 'no_sub':
        has_active = (
            select(Subscription.id)
            .where(Subscription.user_id == User.id, Subscription.status == 'active')
            .correlate(User)
            .exists()
        )
        stmt = select(User).where(~has_active)
    elif target == 'expiring':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(
            Subscription.status == 'active',
            Subscription.end_date <= now + timedelta(days=3),
            Subscription.end_date > now,
        )
    elif target == 'expired':
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(Subscription.status == 'expired')
    elif target.startswith('tariff:'):
        tariff_id = int(target.split(':', 1)[1])
        stmt = select(User).join(Subscription, Subscription.user_id == User.id).where(
            Subscription.status == 'active', Subscription.tariff_id == tariff_id
        )
    else:
        return []

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def _broadcast_target_display_name(db: AsyncSession, target: str) -> str:
    if target in BROADCAST_TARGETS:
        return BROADCAST_TARGETS[target]
    if target.startswith('tariff:'):
        tariff = await db.get(Tariff, int(target.split(':', 1)[1]))
        return f'Тариф «{tariff.name}»' if tariff else 'Тариф (удалён)'
    return target


def _broadcast_target_keyboard() -> InlineKeyboardMarkup:
```

Замените на (обе функции удалены; алиасы из Step 2 их заменяют — вызовы `_broadcast_target_users(...)`
и `_broadcast_target_display_name(...)` дальше по файлу продолжают работать без изменений):

```python
def _broadcast_target_keyboard() -> InlineKeyboardMarkup:
```

- [ ] **Step 5: `admin.py` — удалить `_broadcast_result_keyboard`**

Найдите:

```python
def _broadcast_result_keyboard(selected: list[str]) -> InlineKeyboardMarkup | None:
    ordered_keys = [k for row in BROADCAST_BUTTON_ROWS for k in row if k in selected]
    if not ordered_keys:
        return None
    rows = [[InlineKeyboardButton(text=BROADCAST_BUTTONS[k]['text'], callback_data=BROADCAST_BUTTONS[k]['callback'])] for k in ordered_keys]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == CB_ADMIN_BROADCAST)
```

Замените на:

```python
@router.callback_query(F.data == CB_ADMIN_BROADCAST)
```

- [ ] **Step 6: Тесты проходят БЕЗ РЕДАКТИРОВАНИЯ**

Run: `python -m pytest tests/test_broadcast_golden.py -q -p no:warnings` → 9 passed (тот же файл, ни строки не менялось).
Run: `python -m pytest tests -q -p no:warnings` → 395 passed.
Run: `python -c "import os;os.environ['BOT_TOKEN']='1:t'; import main; print('import ok')"` → `import ok`.

- [ ] **Step 7: Мутационная проверка (сделать → тест падает → откатить)**

1. В `broadcast_service.target_users` поменяйте `elif target == 'expired':` на `elif target == 'expired2':`
   — `test_pick_target_shows_count_and_prompts_for_text` НЕ должен упасть (он не использует
   `expired`), но `python -m pytest tests -q -p no:warnings` должен показать НОЛЬ новых падений
   только если ни один тест не проверяет `expired` — если какой-то тест упал, это ожидаемо;
   верните код.
2. В `result_keyboard` замените `if not ordered_keys:` на `if ordered_keys:` — должен упасть
   `test_continue_shows_preview_with_audience_text_and_buttons` (пустая клавиатура вместо кнопки).
   Верните код.

- [ ] **Step 8: Коммит**

```bash
git add app/services/broadcast_service.py app/handlers/admin.py
git commit -m "Выносит аудитории и кнопки рассылки в общий сервис broadcast_service"
```

---

### Task 3: Отправка, прогресс, отмена — продолжение `broadcast_service.py`

**Files:**
- Modify: `app/services/broadcast_service.py`
- Create: `tests/test_broadcast_service.py`

**Interfaces:**
- Consumes: `target_users`, `target_display_name`, `result_keyboard`, `BROADCAST_TARGETS`,
  `DEFAULT_BROADCAST_BUTTONS` (Task 2, тот же файл).
- Produces: `async start_broadcast(db, bot, *, admin, target, text, media_type=None,
  media_file_id=None, selected_buttons=None, on_progress=None) -> BroadcastHistory` (фоновая
  задача, не ждёт), `async run_broadcast_now(...) -> BroadcastHistory` (та же сигнатура, ждёт
  завершения целиком — для бота), `async cancel_broadcast(db, history_id) -> BroadcastHistory`,
  `async mark_interrupted_broadcasts() -> int`, `BroadcastAlreadyRunningError`,
  `BroadcastNotFoundError`, `BroadcastNotRunningError` — использует Task 4 (бот) и Task 5 (API).

- [ ] **Step 1: Обновить докстринг модуля**

Найдите:

```python
"""Рассылка по пользователям: аудитории и кнопки-конструктор. Общий код для бота
(app/handlers/admin.py) и веб-админки (app/cabinet/broadcast_routes.py) — единственное место,
где живут категории аудитории и набор кнопок, без дублирования."""
```

Замените на:

```python
"""Рассылка по пользователям: аудитории, кнопки-конструктор, отправка пачками с ретраями,
прогресс и отмена. Единственное место, где живёт логика отправки — бот (app/handlers/admin.py,
через run_broadcast_now — ждёт завершения) и API (app/cabinet/broadcast_routes.py, через
start_broadcast — фоновая задача) вызывают этот же код, никакого дублирования."""
```

- [ ] **Step 2: Обновить блок импортов**

Найдите:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Subscription, Tariff, User
from app.handlers.promocode import CB_PROMO_ENTER
from app.keyboards.main_menu import CB_MENU_MAIN, CB_REFERRAL_MENU, CB_SUBSCRIPTION_MY, CB_SUBSCRIPTION_RENEW, CB_SUPPORT_MENU
```

Замените на:

```python
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import AsyncSessionLocal
from app.database.models import BroadcastHistory, Subscription, Tariff, User
from app.handlers.promocode import CB_PROMO_ENTER
from app.keyboards.main_menu import CB_MENU_MAIN, CB_REFERRAL_MENU, CB_SUBSCRIPTION_MY, CB_SUBSCRIPTION_RENEW, CB_SUPPORT_MENU
from app.logging_setup import get_logger

log = get_logger(__name__)
```

- [ ] **Step 3: Дописать в конец файла**

Допишите в конец `app/services/broadcast_service.py`:

```python
# --- отправка, прогресс, отмена -----------------------------------------------------------------

# Батчи по 25 с паузой 1с — запас от лимита Telegram ~30 msg/sec для бота, с ретраем на FloodWait
# (те же параметры, что были в handlers/admin.py до выноса).
BATCH_SIZE = 25
BATCH_DELAY = 1.0
MAX_RETRIES = 3
PROGRESS_COMMIT_INTERVAL = 5.0

ProgressCallback = Callable[[BroadcastHistory], Awaitable[None]]

# id рассылки -> флаг отмены. Один процесс, поэтому память достаточна; переживает рестарт
# не должна — см. mark_interrupted_broadcasts.
_cancel_flags: dict[int, asyncio.Event] = {}


class BroadcastAlreadyRunningError(Exception):
    """Уже есть рассылка со статусом in_progress — общий Telegram-лимит один на процесс."""


class BroadcastNotFoundError(Exception):
    pass


class BroadcastNotRunningError(Exception):
    """Рассылка уже не in_progress — отменять нечего."""


@dataclass
class _PreparedBroadcast:
    history: BroadcastHistory
    recipient_ids: list[int]
    reply_markup: InlineKeyboardMarkup | None
    cancel_event: asyncio.Event


async def _prepare_broadcast(
    db: AsyncSession,
    *,
    admin: User,
    target: str,
    text: str,
    media_type: str | None,
    media_file_id: str | None,
    selected_buttons: list[str] | None,
) -> _PreparedBroadcast:
    """Общая часть для start_broadcast/run_broadcast_now: проверка «одна рассылка одновременно»,
    подсчёт получателей, создание и коммит строки истории, регистрация флага отмены — ДО того,
    как первое сообщение уйдёт получателю."""
    running = await db.execute(select(BroadcastHistory.id).where(BroadcastHistory.status == 'in_progress').limit(1))
    if running.scalar_one_or_none() is not None:
        raise BroadcastAlreadyRunningError

    recipients = await target_users(db, target)
    recipient_ids = [u.telegram_id for u in recipients]

    history = BroadcastHistory(
        target_type=target,
        message_text=text,
        has_media=bool(media_file_id),
        media_type=media_type if media_file_id else None,
        media_file_id=media_file_id,
        total_count=len(recipient_ids),
        admin_id=admin.id,
        admin_name=admin.username or str(admin.telegram_id),
        status='in_progress',
    )
    db.add(history)
    await db.commit()
    await db.refresh(history)

    selected = selected_buttons if selected_buttons is not None else list(DEFAULT_BROADCAST_BUTTONS)
    reply_markup = result_keyboard(selected)
    cancel_event = asyncio.Event()
    _cancel_flags[history.id] = cancel_event
    log.info('broadcast_started', history_id=history.id, target=target, recipients=len(recipient_ids), admin_id=admin.id)
    return _PreparedBroadcast(history=history, recipient_ids=recipient_ids, reply_markup=reply_markup, cancel_event=cancel_event)


async def _commit_progress(history_id: int, *, sent: int, failed: int, blocked: int) -> BroadcastHistory:
    async with AsyncSessionLocal() as db:
        history = await db.get(BroadcastHistory, history_id)
        history.sent_count = sent
        history.failed_count = failed
        history.blocked_count = blocked
        await db.commit()
        await db.refresh(history)
        return history


async def _finalize(
    history_id: int, *, sent: int, failed: int, blocked: int, blocked_ids: list[int], status: str
) -> BroadcastHistory:
    async with AsyncSessionLocal() as db:
        if blocked_ids:
            await db.execute(update(User).where(User.telegram_id.in_(blocked_ids)).values(blocked_bot=True))
        history = await db.get(BroadcastHistory, history_id)
        history.sent_count = sent
        history.failed_count = failed
        history.blocked_count = blocked
        history.status = status
        history.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(history)
        return history


async def _run(
    bot: Bot,
    history_id: int,
    recipient_ids: list[int],
    *,
    text: str,
    media_type: str | None,
    media_file_id: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    cancel_event: asyncio.Event,
    on_progress: ProgressCallback | None,
) -> BroadcastHistory:
    """Батчами по BATCH_SIZE с паузой BATCH_DELAY; ретрай на flood-control; заблокировавшие
    бота помечаются blocked_bot=True. Прогресс коммитится в БД каждые PROGRESS_COMMIT_INTERVAL
    сек (не только в конце — иначе GET .../{id} не видел бы прогресс долгой рассылки)."""
    sent = failed = blocked = 0
    blocked_ids: list[int] = []
    flood_wait_until = 0.0
    cancelled = False

    async def send_one(telegram_id: int) -> str:
        nonlocal flood_wait_until
        for attempt in range(MAX_RETRIES):
            now = asyncio.get_event_loop().time()
            if flood_wait_until > now:
                await asyncio.sleep(flood_wait_until - now)
            try:
                if media_file_id:
                    send_method = {'photo': bot.send_photo, 'video': bot.send_video, 'document': bot.send_document}[media_type]
                    kwarg = {'photo': 'photo', 'video': 'video', 'document': 'document'}[media_type]
                    if len(text) <= 1024:
                        await send_method(chat_id=telegram_id, **{kwarg: media_file_id}, caption=text, reply_markup=reply_markup)
                    else:
                        await send_method(chat_id=telegram_id, **{kwarg: media_file_id})
                        await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                else:
                    await bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                return 'sent'
            except TelegramRetryAfter as exc:
                flood_wait_until = asyncio.get_event_loop().time() + exc.retry_after + 1
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                return 'blocked'
            except Exception:
                log.warning('broadcast_send_failed', telegram_id=telegram_id, attempt=attempt + 1, exc_info=True)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return 'failed'

    last_commit = 0.0
    try:
        for i in range(0, len(recipient_ids), BATCH_SIZE):
            if cancel_event.is_set():
                cancelled = True
                break
            batch = recipient_ids[i : i + BATCH_SIZE]
            results = await asyncio.gather(*[send_one(tid) for tid in batch], return_exceptions=True)
            for idx, result in enumerate(results):
                if result == 'sent':
                    sent += 1
                elif result == 'blocked':
                    blocked += 1
                    blocked_ids.append(batch[idx])
                else:
                    failed += 1

            now = asyncio.get_event_loop().time()
            if now - last_commit >= PROGRESS_COMMIT_INTERVAL:
                last_commit = now
                history = await _commit_progress(history_id, sent=sent, failed=failed, blocked=blocked)
                if on_progress is not None:
                    await on_progress(history)
            await asyncio.sleep(BATCH_DELAY)
    finally:
        _cancel_flags.pop(history_id, None)

    final_status = 'cancelled' if cancelled else ('completed' if failed == 0 and blocked == 0 else 'partial')
    history = await _finalize(history_id, sent=sent, failed=failed, blocked=blocked, blocked_ids=blocked_ids, status=final_status)
    log.info('broadcast_finished', history_id=history_id, status=final_status, sent=sent, failed=failed, blocked=blocked)
    if on_progress is not None:
        await on_progress(history)
    return history


async def start_broadcast(
    db: AsyncSession,
    bot: Bot,
    *,
    admin: User,
    target: str,
    text: str,
    media_type: str | None = None,
    media_file_id: str | None = None,
    selected_buttons: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> BroadcastHistory:
    """Создаёт запись истории и запускает отправку ФОНОВОЙ задачей — не дожидается её
    завершения (для API: ответ 202 сразу, прогресс — через GET .../{id})."""
    prepared = await _prepare_broadcast(
        db, admin=admin, target=target, text=text, media_type=media_type,
        media_file_id=media_file_id, selected_buttons=selected_buttons,
    )
    asyncio.create_task(
        _run(
            bot, prepared.history.id, prepared.recipient_ids, text=text, media_type=media_type,
            media_file_id=media_file_id, reply_markup=prepared.reply_markup,
            cancel_event=prepared.cancel_event, on_progress=on_progress,
        ),
        name=f'broadcast-{prepared.history.id}',
    )
    return prepared.history


async def run_broadcast_now(
    db: AsyncSession,
    bot: Bot,
    *,
    admin: User,
    target: str,
    text: str,
    media_type: str | None = None,
    media_file_id: str | None = None,
    selected_buttons: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> BroadcastHistory:
    """Как start_broadcast, но ДОЖИДАЕТСЯ отправки целиком — бот уже занимает экран прогрессом,
    синхронное ожидание не хуже прежнего инлайн-цикла."""
    prepared = await _prepare_broadcast(
        db, admin=admin, target=target, text=text, media_type=media_type,
        media_file_id=media_file_id, selected_buttons=selected_buttons,
    )
    return await _run(
        bot, prepared.history.id, prepared.recipient_ids, text=text, media_type=media_type,
        media_file_id=media_file_id, reply_markup=prepared.reply_markup,
        cancel_event=prepared.cancel_event, on_progress=on_progress,
    )


async def cancel_broadcast(db: AsyncSession, history_id: int) -> BroadcastHistory:
    """Просит отправку остановиться перед следующей пачкой — уже отправленные сообщения не
    откатываются. Работает независимо от того, кто запустил рассылку (бот или API) — флаг
    один на процесс, по id."""
    history = await db.get(BroadcastHistory, history_id)
    if history is None:
        raise BroadcastNotFoundError
    if history.status != 'in_progress':
        raise BroadcastNotRunningError
    event = _cancel_flags.get(history_id)
    if event is not None:
        event.set()
    return history


async def mark_interrupted_broadcasts() -> int:
    """При старте процесса: если он упал/перезапустился посреди рассылки, ничего не
    возобновляем — только помечаем зависшие записи interrupted, иначе они навсегда блокировали
    бы правило «одна рассылка одновременно» (см. спеку, раздел «Перезапуск процесса»)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(BroadcastHistory)
            .where(BroadcastHistory.status == 'in_progress')
            .values(status='interrupted', completed_at=datetime.now(timezone.utc))
        )
        await db.commit()
        count = result.rowcount or 0
    if count:
        log.warning('broadcast_marked_interrupted', count=count)
    return count
```

- [ ] **Step 4: Написать тесты сервиса**

Создайте `tests/test_broadcast_service.py`:

```python
"""broadcast_service: одна рассылка одновременно, прогресс, отмена, восстановление после
рестарта. Поведение самой отправки (батчи/ретраи/медиа) уже покрыто tests/test_broadcast_golden.py
через run_broadcast_now — здесь проверяется то, что golden-тесты не видят: start_broadcast
(фоновая задача), cancel_broadcast, mark_interrupted_broadcasts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.database.models import BroadcastHistory, User
from app.services import broadcast_service as bs
from tests.helpers import make_user


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(bs, 'AsyncSessionLocal', session_factory)
    yield
    bs._cancel_flags.clear()


async def _await_background_tasks() -> None:
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


def test_start_broadcast_returns_immediately_and_finishes_in_background(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=1, is_admin=True)
        await make_user(session_factory, telegram_id=2)
        await make_user(session_factory, telegram_id=3)
        bot = AsyncMock()

        async with session_factory() as db:
            admin = await db.get(User, admin_id)
            history = await bs.start_broadcast(db, bot, admin=admin, target='all', text='Привет')
            assert history.status == 'in_progress'
            assert history.total_count == 2

        await _await_background_tasks()

        async with session_factory() as db:
            row = await db.get(BroadcastHistory, history.id)
            assert row.status == 'completed'
            assert row.sent_count == 2

    asyncio.run(scenario())


def test_second_broadcast_is_rejected_while_first_is_in_progress(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=1, is_admin=True)
        async with session_factory() as db:
            db.add(BroadcastHistory(target_type='all', message_text='x', total_count=0, status='in_progress'))
            await db.commit()

        async with session_factory() as db:
            admin = await db.get(User, admin_id)
            with pytest.raises(bs.BroadcastAlreadyRunningError):
                await bs.start_broadcast(db, AsyncMock(), admin=admin, target='all', text='Второй')

    asyncio.run(scenario())


def test_cancel_before_the_loop_starts_sends_nothing(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=1, is_admin=True)
        for tg_id in range(2, 7):
            await make_user(session_factory, telegram_id=tg_id)
        bot = AsyncMock()

        async with session_factory() as db:
            admin = await db.get(User, admin_id)
            history = await bs.start_broadcast(db, bot, admin=admin, target='all', text='Отменённая')
            await bs.cancel_broadcast(db, history.id)

        await _await_background_tasks()

        async with session_factory() as db:
            row = await db.get(BroadcastHistory, history.id)
            assert row.status == 'cancelled'
            assert row.sent_count == 0
        bot.send_message.assert_not_awaited()

    asyncio.run(scenario())


def test_cancel_unknown_broadcast_raises_not_found(session_factory):
    async def scenario():
        async with session_factory() as db:
            with pytest.raises(bs.BroadcastNotFoundError):
                await bs.cancel_broadcast(db, 999999)

    asyncio.run(scenario())


def test_cancel_already_finished_broadcast_raises_not_running(session_factory):
    async def scenario():
        async with session_factory() as db:
            history = BroadcastHistory(target_type='all', message_text='x', total_count=0, status='completed')
            db.add(history)
            await db.commit()
            await db.refresh(history)
            with pytest.raises(bs.BroadcastNotRunningError):
                await bs.cancel_broadcast(db, history.id)

    asyncio.run(scenario())


def test_run_broadcast_now_waits_for_completion_and_returns_final_row(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, telegram_id=1, is_admin=True)
        await make_user(session_factory, telegram_id=2)
        bot = AsyncMock()

        async with session_factory() as db:
            admin = await db.get(User, admin_id)
            history = await bs.run_broadcast_now(db, bot, admin=admin, target='all', text='Синхронно')
            assert history.status == 'completed'
            assert history.sent_count == 1

    asyncio.run(scenario())


def test_mark_interrupted_broadcasts_marks_stale_in_progress_rows(session_factory):
    async def scenario():
        async with session_factory() as db:
            db.add(BroadcastHistory(target_type='all', message_text='x', total_count=1, status='in_progress'))
            db.add(BroadcastHistory(target_type='all', message_text='y', total_count=1, status='completed'))
            await db.commit()

        count = await bs.mark_interrupted_broadcasts()
        assert count == 1

        async with session_factory() as db:
            rows = (await db.execute(__import__('sqlalchemy').select(BroadcastHistory))).scalars().all()
            statuses = sorted(r.status for r in rows)
            assert statuses == ['completed', 'interrupted']

    asyncio.run(scenario())
```

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests/test_broadcast_service.py -q -p no:warnings` → 7 passed.
Run: `python -m pytest tests -q -p no:warnings` → 402 passed (395 + 7).

- [ ] **Step 6: Мутационная проверка**

1. В `cancel_broadcast` замените `if history.status != 'in_progress':` на
   `if history.status == 'in_progress':` — должны упасть `test_cancel_already_finished_broadcast_raises_not_running`
   И `test_cancel_before_the_loop_starts_sends_nothing`. Верните код.
2. В `_run` уберите строку `if cancel_event.is_set(): cancelled = True; break` (замените на `pass`)
   — должен упасть `test_cancel_before_the_loop_starts_sends_nothing`. Верните код.
3. В `_prepare_broadcast` уберите проверку `if running.scalar_one_or_none() is not None: raise
   BroadcastAlreadyRunningError` — должен упасть `test_second_broadcast_is_rejected_while_first_is_in_progress`.
   Верните код.

- [ ] **Step 7: Коммит**

```bash
git add app/services/broadcast_service.py tests/test_broadcast_service.py
git commit -m "Добавляет отправку, прогресс и отмену рассылки в broadcast_service"
```

---

### Task 4: Бот переходит на `broadcast_service`; пометка прерванных рассылок при старте

**Files:**
- Modify: `app/handlers/admin.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `broadcast_service.run_broadcast_now`, `broadcast_service.BroadcastAlreadyRunningError`,
  `broadcast_service.mark_interrupted_broadcasts` (Task 3).
- Produces: ничего нового — golden-тесты Task 1 остаются ИСТОЧНИКОМ ИСТИНЫ для этого шага.

- [ ] **Step 1: `admin.py` — убрать `import asyncio` и `TelegramRetryAfter`**

Найдите:

```python
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
```

Замените на:

```python
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramForbiddenError
```

(`asyncio` и `TelegramRetryAfter` в файле использовались только внутри цикла отправки,
который в Step 2 переезжает в `broadcast_service` — после Step 2 в файле не останется ни одного
`asyncio.`/`TelegramRetryAfter` и лишний импорт будет мёртвым кодом.)

- [ ] **Step 2: `admin.py` — переписать `cb_admin_broadcast_confirm`**

Найдите (весь хендлер, от декоратора до строки перед `@router.callback_query(F.data.startswith(CB_BROADCAST_HISTORY))`):

```python
@router.callback_query(AdminBroadcastStates.confirming, F.data == CB_BROADCAST_CONFIRM)
async def cb_admin_broadcast_confirm(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    data = await state.get_data()
    target = data['broadcast_target']
    text = data.get('broadcast_text')
    selected = data.get('selected_buttons') or list(DEFAULT_BROADCAST_BUTTONS)
    has_media = data.get('has_media', False)
    media_type = data.get('media_type')
    media_file_id = data.get('media_file_id')
    await state.clear()
    if not text:
        await callback.answer()
        return

    await callback.answer('Рассылка запущена…')
    await _answer_or_edit(callback, '📨 Подготовка рассылки…', None)

    users = await _broadcast_target_users(db, target)
    recipient_ids = [u.telegram_id for u in users]

    history = BroadcastHistory(
        target_type=target,
        message_text=text,
        has_media=has_media,
        media_type=media_type,
        media_file_id=media_file_id,
        total_count=len(recipient_ids),
        admin_id=db_user.id,
        admin_name=db_user.username or str(db_user.telegram_id),
        status='in_progress',
    )
    db.add(history)
    await db.commit()

    reply_markup = _broadcast_result_keyboard(selected)

    # Батчи по 25 с паузой 1с — те же параметры, что у Bedolaga (запас от лимита
    # Telegram ~30 msg/sec для бота), с ретраем на FloodWait.
    BATCH_SIZE = 25
    BATCH_DELAY = 1.0
    MAX_RETRIES = 3
    flood_wait_until = 0.0

    async def send_one(telegram_id: int) -> str:
        nonlocal flood_wait_until
        for attempt in range(MAX_RETRIES):
            now = asyncio.get_event_loop().time()
            if flood_wait_until > now:
                await asyncio.sleep(flood_wait_until - now)
            try:
                if has_media and media_file_id:
                    send_method = {
                        'photo': callback.bot.send_photo,
                        'video': callback.bot.send_video,
                        'document': callback.bot.send_document,
                    }[media_type]
                    kwarg = {'photo': 'photo', 'video': 'video', 'document': 'document'}[media_type]
                    if len(text) <= 1024:
                        await send_method(chat_id=telegram_id, **{kwarg: media_file_id}, caption=text, reply_markup=reply_markup)
                    else:
                        await send_method(chat_id=telegram_id, **{kwarg: media_file_id})
                        await callback.bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                else:
                    await callback.bot.send_message(chat_id=telegram_id, text=text, reply_markup=reply_markup)
                return 'sent'
            except TelegramRetryAfter as exc:
                flood_wait_until = asyncio.get_event_loop().time() + exc.retry_after + 1
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                return 'blocked'
            except Exception:
                logger.debug('Ошибка отправки рассылки %s (попытка %s)', telegram_id, attempt + 1, exc_info=True)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return 'failed'

    sent_count = failed_count = blocked_count = 0
    blocked_ids: list[int] = []
    last_progress = 0.0
    progress_message = callback.message

    for batch_idx, i in enumerate(range(0, len(recipient_ids), BATCH_SIZE)):
        batch = recipient_ids[i : i + BATCH_SIZE]
        results = await asyncio.gather(*[send_one(tid) for tid in batch], return_exceptions=True)
        for idx, result in enumerate(results):
            if result == 'sent':
                sent_count += 1
            elif result == 'blocked':
                blocked_count += 1
                blocked_ids.append(batch[idx])
            else:
                failed_count += 1

        now = asyncio.get_event_loop().time()
        if now - last_progress >= 5.0:
            last_progress = now
            processed = sent_count + failed_count + blocked_count
            percent = round(processed / len(recipient_ids) * 100, 1) if recipient_ids else 100
            bar = '█' * int(20 * processed / max(len(recipient_ids), 1)) + '░' * (20 - int(20 * processed / max(len(recipient_ids), 1)))
            try:
                await progress_message.edit_text(
                    f'📨 <b>Рассылка в процессе...</b>\n\n[{bar}] {percent}%\n\n'
                    f'Отправлено: {sent_count} · Заблокировали: {blocked_count} · Ошибок: {failed_count}\n'
                    f'Обработано: {processed}/{len(recipient_ids)}'
                )
            except Exception:
                pass
        await asyncio.sleep(BATCH_DELAY)

    if blocked_ids:
        await db.execute(update(User).where(User.telegram_id.in_(blocked_ids)).values(blocked_bot=True))

    history.sent_count = sent_count
    history.failed_count = failed_count
    history.blocked_count = blocked_count
    history.status = 'completed' if failed_count == 0 and blocked_count == 0 else 'partial'
    history.completed_at = datetime.now(timezone.utc)
    await db.commit()

    success_rate = round(sent_count / len(recipient_ids) * 100, 1) if recipient_ids else 0
    result_text = (
        f'✅ <b>Рассылка завершена!</b>\n\n📊 Отправлено: {sent_count}\n'
        f'🚫 Заблокировали бота: {blocked_count}\n❌ Не доставлено: {failed_count}\n'
        f'👥 Всего: {len(recipient_ids)}\n📈 Успешность: {success_rate}%'
    )
    try:
        await progress_message.edit_text(result_text, reply_markup=_back_keyboard())
    except Exception:
        await callback.message.answer(result_text, reply_markup=_back_keyboard())


@router.callback_query(F.data.startswith(CB_BROADCAST_HISTORY))
```

Замените на:

```python
@router.callback_query(AdminBroadcastStates.confirming, F.data == CB_BROADCAST_CONFIRM)
async def cb_admin_broadcast_confirm(callback: CallbackQuery, db: AsyncSession, db_user: User | None, state: FSMContext) -> None:
    if not _is_admin(db_user):
        await callback.answer()
        return
    data = await state.get_data()
    target = data['broadcast_target']
    text = data.get('broadcast_text')
    selected = data.get('selected_buttons') or list(DEFAULT_BROADCAST_BUTTONS)
    has_media = data.get('has_media', False)
    media_type = data.get('media_type')
    media_file_id = data.get('media_file_id')
    await state.clear()
    if not text:
        await callback.answer()
        return

    await callback.answer('Рассылка запущена…')
    await _answer_or_edit(callback, '📨 Подготовка рассылки…', None)
    progress_message = callback.message

    async def on_progress(history: BroadcastHistory) -> None:
        processed = history.sent_count + history.failed_count + history.blocked_count
        percent = round(processed / history.total_count * 100, 1) if history.total_count else 100
        filled = int(20 * processed / max(history.total_count, 1))
        bar = '█' * filled + '░' * (20 - filled)

        if history.status == 'in_progress':
            try:
                await progress_message.edit_text(
                    f'📨 <b>Рассылка в процессе...</b>\n\n[{bar}] {percent}%\n\n'
                    f'Отправлено: {history.sent_count} · Заблокировали: {history.blocked_count} · Ошибок: {history.failed_count}\n'
                    f'Обработано: {processed}/{history.total_count}'
                )
            except Exception:
                pass
            return

        success_rate = round(history.sent_count / history.total_count * 100, 1) if history.total_count else 0
        header = '⏹ <b>Рассылка остановлена.</b>' if history.status == 'cancelled' else '✅ <b>Рассылка завершена!</b>'
        result_text = (
            f'{header}\n\n📊 Отправлено: {history.sent_count}\n'
            f'🚫 Заблокировали бота: {history.blocked_count}\n❌ Не доставлено: {history.failed_count}\n'
            f'👥 Всего: {history.total_count}\n📈 Успешность: {success_rate}%'
        )
        try:
            await progress_message.edit_text(result_text, reply_markup=_back_keyboard())
        except Exception:
            await callback.message.answer(result_text, reply_markup=_back_keyboard())

    try:
        await broadcast_service.run_broadcast_now(
            db,
            callback.bot,
            admin=db_user,
            target=target,
            text=text,
            media_type=media_type if has_media else None,
            media_file_id=media_file_id if has_media else None,
            selected_buttons=selected,
            on_progress=on_progress,
        )
    except broadcast_service.BroadcastAlreadyRunningError:
        await progress_message.edit_text(
            '⚠️ Уже выполняется другая рассылка — дождитесь её завершения.', reply_markup=_back_keyboard()
        )


@router.callback_query(F.data.startswith(CB_BROADCAST_HISTORY))
```

- [ ] **Step 3: Golden-тесты проходят БЕЗ РЕДАКТИРОВАНИЯ**

Run: `python -m pytest tests/test_broadcast_golden.py -q -p no:warnings` → 9 passed (файл не тронут).
Run: `python -m pytest tests -q -p no:warnings` → 402 passed.
Run: `python -c "import os;os.environ['BOT_TOKEN']='1:t'; import main; print('import ok')"` → `import ok`.

Если что-то из golden упало — не редактируйте `tests/test_broadcast_golden.py`, чините код: текст
`on_progress`/порядок вызовов должны воспроизводить старый инлайн-цикл посимвольно.

- [ ] **Step 4: `main.py` — пометка прерванных рассылок при старте**

Найдите:

```python
    await init_sqlite_pragmas()
    await _warn_if_no_active_tariff()

    bot, dp = await setup_bot()
```

Замените на:

```python
    await init_sqlite_pragmas()
    await _warn_if_no_active_tariff()

    from app.services.broadcast_service import mark_interrupted_broadcasts

    await mark_interrupted_broadcasts()

    bot, dp = await setup_bot()
```

- [ ] **Step 5: Мутационная проверка**

В `on_progress` (внутри `cb_admin_broadcast_confirm`) поменяйте
`header = '⏹ <b>Рассылка остановлена.</b>' if history.status == 'cancelled' else '✅ <b>Рассылка завершена!</b>'`
на константу `header = '✅ <b>Рассылка завершена!</b>'` — тест на cancel в боте план не требует
(отмена из бота не проверяется golden-тестами), поэтому просто прогоните
`python -m pytest tests -q -p no:warnings` и убедитесь, что ничего не упало (эта ветка правда не
покрыта тестами бота — работоспособность текста для статуса `cancelled` проверяется вручную при
следующем ручном тестировании, отметьте это как известное ограничение, не блокирующее план).
Верните код.

- [ ] **Step 6: Коммит**

```bash
git add app/handlers/admin.py main.py
git commit -m "Переводит рассылку бота на broadcast_service и помечает прерванные рассылки при старте"
```

---

### Task 5: API `/cabinet/admin/broadcasts/*`

**Files:**
- Create: `app/cabinet/broadcast_schemas.py`
- Create: `app/cabinet/broadcast_routes.py`
- Create: `tests/test_broadcast_api.py`
- Modify: `app/cabinet/app.py`

**Interfaces:**
- Consumes: `broadcast_service.{target_users, target_display_name, start_broadcast,
  cancel_broadcast, BROADCAST_TARGETS, BROADCAST_BUTTONS, ALLOWED_MEDIA_TYPES,
  BroadcastAlreadyRunningError, BroadcastNotFoundError, BroadcastNotRunningError}` (Tasks 2-3),
  `app.handlers.subscription.get_active_tariffs`, `app.cabinet.admin_deps.require_admin`,
  `app.cabinet.deps.get_db`.
- Produces: маршруты, используемые фронтендом (см. спеку).

- [ ] **Step 1: Создать `app/cabinet/broadcast_schemas.py`**

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BroadcastTargetOut(BaseModel):
    key: str
    label: str
    recipient_count: int


class BroadcastTariffOut(BaseModel):
    id: int
    name: str
    recipient_count: int


class BroadcastButtonOut(BaseModel):
    key: str
    label: str


class BroadcastOptionsResponse(BaseModel):
    targets: list[BroadcastTargetOut]
    tariffs: list[BroadcastTariffOut]
    buttons: list[BroadcastButtonOut]


class BroadcastPreviewRequest(BaseModel):
    target: str


class BroadcastPreviewResponse(BaseModel):
    target_display_name: str
    recipient_count: int


class BroadcastCreateRequest(BaseModel):
    target: str
    text: str = Field(min_length=1, max_length=4000)
    media_type: str | None = None
    media_file_id: str | None = None
    buttons: list[str] = Field(default_factory=lambda: ['home'])


class BroadcastOut(BaseModel):
    id: int
    status: str
    target_type: str
    target_display_name: str
    total_count: int
    sent_count: int
    failed_count: int
    blocked_count: int
    has_media: bool
    media_type: str | None
    admin_name: str | None
    created_at: datetime
    completed_at: datetime | None


class BroadcastListResponse(BaseModel):
    items: list[BroadcastOut]
    total: int
    page: int
    total_pages: int
```

- [ ] **Step 2: Создать `app/cabinet/broadcast_routes.py`**

```python
"""/cabinet/admin/broadcasts/* — рассылки по пользователям из веб-админки. Логика отправки —
в app/services/broadcast_service.py, общая с ботом (app/handlers/admin.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cabinet.admin_deps import require_admin
from app.cabinet.broadcast_schemas import (
    BroadcastButtonOut,
    BroadcastCreateRequest,
    BroadcastListResponse,
    BroadcastOptionsResponse,
    BroadcastOut,
    BroadcastPreviewRequest,
    BroadcastPreviewResponse,
    BroadcastTargetOut,
    BroadcastTariffOut,
)
from app.cabinet.deps import get_db
from app.database.models import BroadcastHistory, Tariff, User
from app.handlers.subscription import get_active_tariffs
from app.services import broadcast_service
from app.services.broadcast_service import (
    ALLOWED_MEDIA_TYPES,
    BROADCAST_BUTTONS,
    BROADCAST_TARGETS,
    BroadcastAlreadyRunningError,
    BroadcastNotFoundError,
    BroadcastNotRunningError,
)

router = APIRouter(prefix='/cabinet/admin/broadcasts')

PAGE_SIZE = 20


async def _valid_target_or_400(db: AsyncSession, target: str) -> None:
    if target in BROADCAST_TARGETS:
        return
    if target.startswith('tariff:'):
        rest = target.split(':', 1)[1]
        if rest.isdigit() and await db.get(Tariff, int(rest)) is not None:
            return
    raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Неизвестная аудитория')


def _to_out(history: BroadcastHistory, target_display_name: str) -> BroadcastOut:
    return BroadcastOut(
        id=history.id,
        status=history.status,
        target_type=history.target_type,
        target_display_name=target_display_name,
        total_count=history.total_count,
        sent_count=history.sent_count,
        failed_count=history.failed_count,
        blocked_count=history.blocked_count,
        has_media=history.has_media,
        media_type=history.media_type,
        admin_name=history.admin_name,
        created_at=history.created_at,
        completed_at=history.completed_at,
    )


@router.get('/options', response_model=BroadcastOptionsResponse)
async def get_options(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> BroadcastOptionsResponse:
    targets = [
        BroadcastTargetOut(key=key, label=label, recipient_count=len(await broadcast_service.target_users(db, key)))
        for key, label in BROADCAST_TARGETS.items()
    ]
    tariffs = [
        BroadcastTariffOut(id=t.id, name=t.name, recipient_count=len(await broadcast_service.target_users(db, f'tariff:{t.id}')))
        for t in await get_active_tariffs(db)
    ]
    buttons = [BroadcastButtonOut(key=key, label=value['text']) for key, value in BROADCAST_BUTTONS.items()]
    return BroadcastOptionsResponse(targets=targets, tariffs=tariffs, buttons=buttons)


@router.post('/preview', response_model=BroadcastPreviewResponse)
async def preview_broadcast(
    payload: BroadcastPreviewRequest, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> BroadcastPreviewResponse:
    await _valid_target_or_400(db, payload.target)
    users = await broadcast_service.target_users(db, payload.target)
    name = await broadcast_service.target_display_name(db, payload.target)
    return BroadcastPreviewResponse(target_display_name=name, recipient_count=len(users))


@router.post('/', response_model=BroadcastOut, status_code=status.HTTP_202_ACCEPTED)
async def create_broadcast(
    payload: BroadcastCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> BroadcastOut:
    await _valid_target_or_400(db, payload.target)
    if payload.media_file_id and payload.media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Недопустимый тип медиа')
    unknown_buttons = set(payload.buttons) - BROADCAST_BUTTONS.keys()
    if unknown_buttons:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f'Неизвестные кнопки: {", ".join(sorted(unknown_buttons))}')
    try:
        history = await broadcast_service.start_broadcast(
            db,
            request.app.state.bot,
            admin=admin,
            target=payload.target,
            text=payload.text,
            media_type=payload.media_type,
            media_file_id=payload.media_file_id,
            selected_buttons=payload.buttons,
        )
    except BroadcastAlreadyRunningError:
        raise HTTPException(status.HTTP_409_CONFLICT, 'Рассылка уже выполняется') from None
    name = await broadcast_service.target_display_name(db, payload.target)
    return _to_out(history, name)


@router.get('/', response_model=BroadcastListResponse)
async def list_broadcasts(
    page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> BroadcastListResponse:
    total = (await db.execute(select(func.count(BroadcastHistory.id)))).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    rows = (
        await db.execute(
            select(BroadcastHistory).order_by(BroadcastHistory.created_at.desc()).limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)
        )
    ).scalars().all()
    items = [_to_out(row, await broadcast_service.target_display_name(db, row.target_type)) for row in rows]
    return BroadcastListResponse(items=items, total=total, page=page, total_pages=total_pages)


@router.get('/{broadcast_id}', response_model=BroadcastOut)
async def get_broadcast(
    broadcast_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> BroadcastOut:
    history = await db.get(BroadcastHistory, broadcast_id)
    if history is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Рассылка не найдена')
    name = await broadcast_service.target_display_name(db, history.target_type)
    return _to_out(history, name)


@router.post('/{broadcast_id}/cancel', status_code=status.HTTP_202_ACCEPTED)
async def cancel_broadcast_route(
    broadcast_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    try:
        await broadcast_service.cancel_broadcast(db, broadcast_id)
    except BroadcastNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Рассылка не найдена') from None
    except BroadcastNotRunningError:
        raise HTTPException(status.HTTP_409_CONFLICT, 'Рассылка уже завершена') from None
    return {'status': 'cancelling'}
```

- [ ] **Step 3: Зарегистрировать роутер**

В `app/cabinet/app.py` найдите:

```python
from app.cabinet.admin_routes import router as admin_router
from app.cabinet.notifications_routes import router as notifications_router
```

Замените на:

```python
from app.cabinet.admin_routes import router as admin_router
from app.cabinet.broadcast_routes import router as broadcast_router
from app.cabinet.notifications_routes import router as notifications_router
```

Найдите:

```python
    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(notifications_router)
```

Замените на:

```python
    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(broadcast_router)
    app.include_router(notifications_router)
```

- [ ] **Step 4: Написать тесты API**

Создайте `tests/test_broadcast_api.py` (фикстура `api` — тот же паттерн, что
`tests/test_notifications_api.py`):

```python
"""API рассылок для веб-админки."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cabinet.admin_deps import require_admin
from app.cabinet.app import create_app
from app.cabinet.deps import get_db
from app.database.models import BroadcastHistory, User
from app.services import broadcast_service as bs
from tests.helpers import make_tariff, make_user

BASE = '/cabinet/admin/broadcasts'


@pytest.fixture
def api(session_factory, monkeypatch):
    monkeypatch.setattr(bs, 'AsyncSessionLocal', session_factory)
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
    bs._cancel_flags.clear()


async def _await_background_tasks() -> None:
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


def test_options_lists_targets_tariffs_and_buttons(api):
    response = api.get(f'{BASE}/options')

    assert response.status_code == 200
    data = response.json()
    assert {t['key'] for t in data['targets']} == {'all', 'active', 'no_sub', 'expiring', 'expired'}
    assert data['buttons'][0]['key'] == 'subscription'
    assert data['tariffs'] == []


def test_preview_rejects_unknown_target(api):
    response = api.post(f'{BASE}/preview', json={'target': 'nonsense'})
    assert response.status_code == 400


def test_preview_returns_recipient_count(api):
    response = api.post(f'{BASE}/preview', json={'target': 'all'})
    assert response.status_code == 200
    body = response.json()
    assert body['target_display_name'] == '👥 Всем'
    assert body['recipient_count'] == 1  # только сам админ уже создан фикстурой


def test_create_starts_broadcast_and_returns_202(api):
    response = api.post(BASE + '/', json={'target': 'all', 'text': 'Привет!', 'buttons': ['home']})

    assert response.status_code == 202
    body = response.json()
    assert body['status'] == 'in_progress'
    assert body['total_count'] == 1

    async def wait():
        await _await_background_tasks()

    asyncio.run(wait())
    api.bot.send_message.assert_awaited_once()


def test_create_rejects_when_already_running(api):
    api.post(BASE + '/', json={'target': 'all', 'text': 'Первая'})
    response = api.post(BASE + '/', json={'target': 'all', 'text': 'Вторая'})
    assert response.status_code == 409

    async def wait():
        await _await_background_tasks()

    asyncio.run(wait())


def test_create_rejects_unknown_media_type(api):
    response = api.post(BASE + '/', json={'target': 'all', 'text': 'x', 'media_type': 'audio', 'media_file_id': 'F1'})
    assert response.status_code == 400


def test_create_rejects_unknown_button(api):
    response = api.post(BASE + '/', json={'target': 'all', 'text': 'x', 'buttons': ['does_not_exist']})
    assert response.status_code == 400


def test_get_by_id_returns_404_for_unknown(api):
    response = api.get(f'{BASE}/999999')
    assert response.status_code == 404


def test_get_by_id_reflects_progress_after_completion(api):
    create = api.post(BASE + '/', json={'target': 'all', 'text': 'Проверка статуса'})
    broadcast_id = create.json()['id']

    async def wait():
        await _await_background_tasks()

    asyncio.run(wait())

    response = api.get(f'{BASE}/{broadcast_id}')
    assert response.status_code == 200
    assert response.json()['status'] == 'completed'
    assert response.json()['sent_count'] == 1


def test_list_returns_history_with_pagination_fields(api):
    api.post(BASE + '/', json={'target': 'all', 'text': 'В историю'})

    async def wait():
        await _await_background_tasks()

    asyncio.run(wait())

    response = api.get(BASE + '/')
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 1
    assert body['page'] == 1
    assert body['items'][0]['target_display_name'] == '👥 Всем'


def test_cancel_unknown_broadcast_returns_404(api):
    response = api.post(f'{BASE}/999999/cancel')
    assert response.status_code == 404


def test_cancel_stops_before_sending(api):
    create = api.post(BASE + '/', json={'target': 'all', 'text': 'Отмена через API'})
    broadcast_id = create.json()['id']

    cancel = api.post(f'{BASE}/{broadcast_id}/cancel')
    assert cancel.status_code == 202

    async def wait():
        await _await_background_tasks()

    asyncio.run(wait())

    response = api.get(f'{BASE}/{broadcast_id}')
    assert response.json()['status'] == 'cancelled'
    assert response.json()['sent_count'] == 0


def test_cancel_already_finished_returns_409(api):
    create = api.post(BASE + '/', json={'target': 'all', 'text': 'Уже готова'})
    broadcast_id = create.json()['id']

    async def wait():
        await _await_background_tasks()

    asyncio.run(wait())

    response = api.post(f'{BASE}/{broadcast_id}/cancel')
    assert response.status_code == 409
```

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests/test_broadcast_api.py -q -p no:warnings` → 13 passed.
Run: `python -m pytest tests -q -p no:warnings` → 415 passed (402 + 13).
Run: `python -c "import os;os.environ['BOT_TOKEN']='1:t'; import main; print('import ok')"` → `import ok`.

- [ ] **Step 6: Мутационная проверка**

1. В `_valid_target_or_400` уберите `raise HTTPException(...)` в конце (замените на `return`) —
   должен упасть `test_preview_rejects_unknown_target`. Верните код.
2. В `create_broadcast` уберите проверку `unknown_buttons` — должен упасть
   `test_create_rejects_unknown_button`. Верните код.
3. В `cancel_broadcast_route` замените `status.HTTP_404_NOT_FOUND` на `status.HTTP_400_BAD_REQUEST`
   в обработке `BroadcastNotFoundError` — должен упасть `test_cancel_unknown_broadcast_returns_404`.
   Верните код.

- [ ] **Step 7: Коммит**

```bash
git add app/cabinet/broadcast_schemas.py app/cabinet/broadcast_routes.py app/cabinet/app.py tests/test_broadcast_api.py
git commit -m "Добавляет API рассылок: опции, предпросмотр, запуск, список, статус, отмена"
```

---

### Task 6: Документация API и финальные проверки

**Files:**
- Modify: `scripts/generate_api_docs.py`
- Modify: `docs/api/API.md`
- Regenerate: `docs/api/reference-admin.md`, `docs/api/schemas.md`, `docs/api/openapi.json`

**Interfaces:**
- Consumes: все роуты Task 5.
- Produces: актуальная документация для фронтенда (NRW-MiniApp).

- [ ] **Step 1: Добавить описания эндпоинтов в генератор**

В `scripts/generate_api_docs.py` найдите (последнюю `add(...)` строку про уведомления):

```python
add('GET', '/cabinet/admin/notifications/emoji', 'Кастомные эмодзи проекта', 'Список слотов с заданным custom_id — для вставки в текст через `<tg-emoji emoji-id="…">`.')
```

Если такой строки нет дословно — найдите последнюю строку `add(...)` перед `GROUPS_USER = [` и
добавьте после неё:

```python
add('GET', '/cabinet/admin/broadcasts/options', 'Данные для формы рассылки', 'Категории аудитории и тарифы с live-счётчиком получателей, список доступных кнопок-конструктора.')
add('POST', '/cabinet/admin/broadcasts/preview', 'Предпросмотр аудитории', 'Название категории и число получателей без запуска рассылки. `400`, если `target` не входит в известные категории и не `tariff:<id>` существующего тарифа.')
add('POST', '/cabinet/admin/broadcasts/', 'Запустить рассылку', 'Создаёт запись и запускает отправку ФОНОВОЙ задачей — ответ `202` сразу, прогресс через `GET .../{id}`. Не более одной рассылки одновременно: `409`, если уже есть `in_progress`. `media_file_id` — Telegram file_id, полученный где-то ещё (загрузка файла через API не поддерживается). `400` при неизвестной аудитории/типе медиа/кнопке.')
add('GET', '/cabinet/admin/broadcasts/', 'История рассылок', 'Постранично, новые сверху.')
add('GET', '/cabinet/admin/broadcasts/{broadcast_id}', 'Статус рассылки', 'Для опроса прогресса: `total_count`/`sent_count`/`failed_count`/`blocked_count`, `status` (`in_progress`/`completed`/`partial`/`cancelled`/`interrupted`).')
add('POST', '/cabinet/admin/broadcasts/{broadcast_id}/cancel', 'Остановить рассылку', 'Не откатывает уже отправленные сообщения — останавливает перед следующей пачкой. `409`, если рассылка уже не `in_progress`.')
```

- [ ] **Step 2: Добавить группу в `GROUPS_ADMIN`**

Найдите:

```python
    ('Уведомления бота', ['/cabinet/admin/notifications/templates', '/cabinet/admin/notifications/templates/{key}', '/cabinet/admin/notifications/templates/{key}/preview', '/cabinet/admin/notifications/templates/{key}/test', '/cabinet/admin/notifications/emoji']),
]
```

Замените на:

```python
    ('Уведомления бота', ['/cabinet/admin/notifications/templates', '/cabinet/admin/notifications/templates/{key}', '/cabinet/admin/notifications/templates/{key}/preview', '/cabinet/admin/notifications/templates/{key}/test', '/cabinet/admin/notifications/emoji']),
    ('Рассылки', ['/cabinet/admin/broadcasts/options', '/cabinet/admin/broadcasts/preview', '/cabinet/admin/broadcasts/', '/cabinet/admin/broadcasts/{broadcast_id}', '/cabinet/admin/broadcasts/{broadcast_id}/cancel']),
]
```

- [ ] **Step 3: Обновить `docs/api/API.md`**

Добавьте перед разделом «Что изменится (план центра аналитики)» новый раздел:

```markdown
## Рассылки по пользователям

`POST /cabinet/admin/broadcasts/` создаёт рассылку и сразу отвечает `202` — отправка идёт
фоновой задачей. Прогресс — `GET /cabinet/admin/broadcasts/{id}` (опрос; `status`:
`in_progress` → `completed`/`partial`/`cancelled`/`interrupted`). Не более одной рассылки
одновременно (`409`, если уже есть `in_progress`). `POST .../{id}/cancel` останавливает
рассылку перед следующей пачкой получателей — уже отправленные сообщения не откатываются.

Медиа — только `file_id`, уже известный откуда-то ещё (загрузка файла через API не
поддерживается в этой версии). Категории аудиторий и кнопки-конструктор — `GET
/cabinet/admin/broadcasts/options`.

Подробности дизайна — `docs/superpowers/specs/2026-09-22-broadcast-api-design.md`.
```

- [ ] **Step 4: Перегенерировать и проверить**

Run: `BOT_TOKEN=x python scripts/generate_api_docs.py` (PowerShell: `$env:BOT_TOKEN='x';
python scripts/generate_api_docs.py`)
Expected: без ошибок; вывод не сообщает о путях без описания/группы для `/cabinet/admin/broadcasts/*`.

Run: `git diff --stat` — проверьте, что диф в `docs/api/*` содержит только добавления по
рассылкам, без несвязанных изменений (перегенерированные файлы детерминированы — посторонний
диф означает рассинхронизацию с кодом, разберитесь прежде чем коммитить).

- [ ] **Step 5: Финальные проверки**

Run: `python -m pytest tests -q -p no:warnings` → 415 passed.
Run: `python -c "import os;os.environ['BOT_TOKEN']='1:t'; import main; print('import ok')"` → `import ok`.
Run: `grep -rn "_broadcast_target_users\|_broadcast_target_display_name\|_broadcast_result_keyboard" app/handlers/admin.py`
— должны остаться только строки объявления алиасов (Task 2, Step 2) и их использование в
`admin.py`; ни одного места с самостоятельной логикой рассылки вне `broadcast_service.py`.

- [ ] **Step 6: Коммит**

```bash
git add scripts/generate_api_docs.py docs/api/API.md docs/api/reference-admin.md docs/api/schemas.md docs/api/openapi.json
git commit -m "Документирует API рассылок и перегенерирует справочник"
```
