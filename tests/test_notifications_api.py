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
