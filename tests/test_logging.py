"""Логирование: формат, контекст, маскирование секретов, middleware и бизнес-события."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import structlog
from aiogram.types import CallbackQuery, Chat, Message, Update, User as TgUser
from fastapi.testclient import TestClient

from app.cabinet.app import create_app
from app.database.models import Payment, Transaction, User
from app.logging_setup import bind_context, clear_context, get_logger, setup_logging
from app.middlewares.logging import LoggingMiddleware, describe_update
from app.services.balance_service import InsufficientBalanceError, adjust_balance_clamped, credit_balance, debit_balance
from app.services.payment_finalization import finalize_pending_payment
from tests.helpers import make_tariff, make_user

BOT_TOKEN = '123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw'


@pytest.fixture
def out():
    """JSON-логирование в StringIO; после теста возвращает глобальную конфигурацию как была."""
    buffer = io.StringIO()
    setup_logging(level='DEBUG', fmt='json', stream=buffer, secrets=['super-secret-key'])
    clear_context()
    yield buffer
    clear_context()
    structlog.reset_defaults()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)
    for name in ('httpx', 'httpcore', 'aiogram.event', 'aiogram.dispatcher', 'sqlalchemy.engine', 'aiosqlite', 'asyncio', 'uvicorn.access'):
        logging.getLogger(name).setLevel(logging.NOTSET)


def events(buffer: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


def find(buffer: io.StringIO, event: str) -> list[dict]:
    return [entry for entry in events(buffer) if entry['event'] == event]


# --- формат и контекст ---------------------------------------------------------


def test_json_event_has_structure_and_context(out):
    bind_context(telegram_id=5, user_id=7)

    get_logger('app.demo').info('payment_finalized', payment_id=1, amount_kopeks=29900, tariff='Онлайн')

    (entry,) = events(out)
    assert entry['event'] == 'payment_finalized'
    assert entry['level'] == 'info' and entry['logger'] == 'app.demo'
    assert entry['payment_id'] == 1 and entry['tariff'] == 'Онлайн'  # кириллица не экранируется
    assert entry['telegram_id'] == 5 and entry['user_id'] == 7
    assert datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00')).tzinfo is not None


def test_stdlib_logging_goes_through_same_pipeline(out):
    bind_context(user_id=7)

    logging.getLogger('app.services.legacy').warning('Не удалось получить traffic для %s', 'uuid-1')

    (entry,) = events(out)
    assert entry['event'] == 'Не удалось получить traffic для uuid-1'
    assert entry['level'] == 'warning' and entry['logger'] == 'app.services.legacy'
    assert entry['user_id'] == 7


def test_exception_is_logged_with_traceback(out):
    try:
        1 / 0
    except ZeroDivisionError:
        get_logger('app.demo').exception('boom')

    (entry,) = events(out)
    assert entry['level'] == 'error' and 'ZeroDivisionError' in entry['exception']


def test_console_format_is_human_readable():
    buffer = io.StringIO()
    setup_logging(level='INFO', fmt='console', stream=buffer, secrets=[])
    try:
        get_logger('app.demo').info('payment_finalized', payment_id=1, provider='cispay')
    finally:
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()
        logging.getLogger().setLevel(logging.WARNING)

    line = buffer.getvalue()
    assert 'payment_finalized' in line and 'payment_id=1' in line and 'provider=cispay' in line
    assert '\x1b[' not in line  # не терминал — без цветовых кодов


def test_noisy_libraries_are_quiet_but_warnings_pass(out):
    logging.getLogger('httpx').info('HTTP Request: GET https://x "200 OK"')
    logging.getLogger('aiogram.event').info('Update id=1 is handled')
    logging.getLogger('httpx').warning('real problem')

    assert [entry['event'] for entry in events(out)] == ['real problem']


def test_level_filters_debug(out):
    setup_logging(level='INFO', fmt='json', stream=out, secrets=[])

    get_logger('app.demo').debug('hidden')
    get_logger('app.demo').info('shown')

    assert [entry['event'] for entry in events(out)] == ['shown']


# --- маскирование секретов -----------------------------------------------------


def test_secrets_are_redacted_everywhere(out):
    log = get_logger('app.demo')
    log.info('call to https://user:hunter2pass@panel.example/api', header='Bearer super-secret-key', nested={'k': ['super-secret-key']})
    logging.getLogger('legacy').info('token=%s', BOT_TOKEN)

    text = out.getvalue()
    assert 'super-secret-key' not in text and 'hunter2pass' not in text and BOT_TOKEN not in text
    first, second = events(out)
    assert 'user:***@panel.example' in first['event']
    assert first['header'] == 'Bearer ***' and first['nested'] == {'k': ['***']}
    assert second['event'] == 'token=***'


def test_secrets_are_redacted_in_tracebacks(out):
    try:
        raise RuntimeError('failed with key super-secret-key')
    except RuntimeError:
        get_logger('app.demo').exception('boom')

    assert 'super-secret-key' not in out.getvalue()


def test_short_secrets_are_not_masked(out):
    """Слишком короткое значение (например пустой/дефолтный секрет) не должно
    превращать в *** обычные слова."""
    setup_logging(level='INFO', fmt='json', stream=out, secrets=['', 'abc'])

    get_logger('app.demo').info('abc abc')

    assert events(out)[0]['event'] == 'abc abc'


# --- апдейты Telegram ----------------------------------------------------------


def _update(text: str | None = None, callback_data: str | None = None) -> Update:
    user = TgUser(id=5, is_bot=False, first_name='Ivan', username='ivan')
    chat = Chat(id=5, type='private')
    if callback_data is not None:
        message = Message(message_id=1, date=datetime.now(timezone.utc), chat=chat, text='menu')
        return Update(update_id=10, callback_query=CallbackQuery(id='c', from_user=user, chat_instance='x', data=callback_data, message=message))
    return Update(update_id=10, message=Message(message_id=1, date=datetime.now(timezone.utc), chat=chat, from_user=user, text=text))


async def _run_middleware(update: Update, handler) -> None:
    telegram_user = (update.message or update.callback_query).from_user
    await LoggingMiddleware()(handler, update, {'event_from_user': telegram_user})


def test_describe_update_never_contains_free_text():
    assert describe_update(_update('/start ref_SECRET123')) == {'kind': 'command', 'action': '/start'}
    assert describe_update(_update('мой пароль 12345')) == {'kind': 'message', 'action': '<text>'}
    assert describe_update(_update(callback_data='sub:buy:30')) == {'kind': 'callback', 'action': 'sub:buy:30'}


def test_update_is_logged_with_context_and_duration(out):
    async def handler(event, data):
        get_logger('app.handlers').info('inside_handler')  # должен получить контекст апдейта

    asyncio.run(_run_middleware(_update('/start ref_SECRET123'), handler))

    inside, handled = events(out)
    assert inside['telegram_id'] == 5 and inside['update_id'] == 10 and inside['username'] == 'ivan'
    assert handled['event'] == 'update_handled' and handled['kind'] == 'command' and handled['action'] == '/start'
    assert isinstance(handled['duration_ms'], int)
    assert 'ref_SECRET123' not in out.getvalue()


def test_context_does_not_leak_between_updates(out):
    async def scenario():
        bind_context(user_id=99, payment_id=1)  # "остаток" предыдущего апдейта
        await _run_middleware(_update('/menu'), AsyncMock())

    asyncio.run(scenario())

    (entry,) = events(out)
    assert 'user_id' not in entry and 'payment_id' not in entry


def test_failed_update_is_logged_and_reraised(out):
    handler = AsyncMock(side_effect=ValueError('handler bug'))

    with pytest.raises(ValueError):
        asyncio.run(_run_middleware(_update(callback_data='sub:buy:30'), handler))

    (entry,) = events(out)
    assert entry['event'] == 'update_failed' and entry['level'] == 'error'
    assert entry['action'] == 'sub:buy:30' and 'handler bug' in entry['exception']


def test_slow_update_is_a_warning(out, monkeypatch):
    monkeypatch.setattr('app.middlewares.logging.SLOW_UPDATE_SECONDS', 0.0)

    asyncio.run(_run_middleware(_update('/menu'), AsyncMock()))

    assert find(out, 'update_handled')[0]['level'] == 'warning'


# --- HTTP кабинета -------------------------------------------------------------


def test_http_request_is_logged_with_request_id(out):
    with TestClient(create_app(AsyncMock())) as client:
        response = client.get('/cabinet/dashboard?token=leak-me')

    (entry,) = find(out, 'http_request')
    assert response.status_code == 401
    assert entry['path'] == '/cabinet/dashboard' and entry['method'] == 'GET' and entry['status'] == 401
    assert entry['request_id'] == response.headers['X-Request-ID'] and isinstance(entry['duration_ms'], int)
    assert 'leak-me' not in out.getvalue()  # query-строка не логируется


def test_valid_incoming_request_id_is_kept_and_invalid_is_replaced(out):
    with TestClient(create_app(AsyncMock())) as client:
        kept = client.get('/cabinet/dashboard', headers={'X-Request-ID': 'trace-abc.123'})
        replaced = client.get('/cabinet/dashboard', headers={'X-Request-ID': 'bad id\twith spaces'})

    assert kept.headers['X-Request-ID'] == 'trace-abc.123'
    assert replaced.headers['X-Request-ID'] != 'bad id\twith spaces' and len(replaced.headers['X-Request-ID']) == 12


def test_health_checks_do_not_spam_info_logs(out):
    with TestClient(create_app(AsyncMock())) as client:
        client.get('/health')

    (entry,) = find(out, 'http_request')
    assert entry['level'] == 'debug'


# --- бизнес-события ------------------------------------------------------------


def test_balance_changes_are_logged_with_reason(session_factory, out):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=1000)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            await credit_balance(db, user, 500, reason='promocode')
            await debit_balance(db, user, 200, reason='subscription_purchase')
            with pytest.raises(InsufficientBalanceError):
                await debit_balance(db, user, 10_000, reason='subscription_purchase')
            await adjust_balance_clamped(db, user, -5000, reason='admin_adjustment')
        return user_id

    user_id = asyncio.run(scenario())

    changes = find(out, 'balance_changed')
    assert [(c['reason'], c['delta_kopeks'], c['balance_kopeks']) for c in changes] == [
        ('promocode', 500, 1500),
        ('subscription_purchase', -200, 1300),
        ('admin_adjustment', -1300, 0),
    ]
    assert all(c['user_id'] == user_id for c in changes)
    (rejected,) = find(out, 'balance_insufficient')
    assert rejected['level'] == 'warning' and rejected['need_kopeks'] == 10_000


def test_payment_finalization_is_logged(session_factory, out):
    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory, name='Онлайн')
        async with session_factory() as db:
            transaction = Transaction(user_id=user_id, type='subscription_payment', amount_kopeks=10000, status='pending')
            db.add(transaction)
            await db.flush()
            payment = Payment(
                user_id=user_id, transaction_id=transaction.id, provider='cispay', external_id='e1', amount_kopeks=10000,
                status='pending', raw_payload={'kind': 'subscription', 'tariff_id': tariff_id, 'period_days': 30},
            )
            db.add(payment)
            await db.commit()
        async with session_factory() as db:
            payment = await db.get(Payment, payment.id)
            await finalize_pending_payment(db, payment, AsyncMock())
            await finalize_pending_payment(db, payment, AsyncMock())  # повтор
        return payment.id

    payment_id = asyncio.run(scenario())

    (finalized,) = find(out, 'payment_finalized')
    assert finalized['payment_id'] == payment_id and finalized['provider'] == 'cispay' and finalized['tariff'] == 'Онлайн'
    assert finalized['amount_kopeks'] == 10000 and finalized['period_days'] == 30
    assert len(find(out, 'subscription_created')) == 1
    assert len(find(out, 'payment_already_processed')) == 1
