"""POST /cabinet/admin/users/{id}/revoke-subscription: перевыпуск доступа в Remnawave (ссылка+пароли либо только
пароли), запись новой ссылки в БД (Mini App берёт её оттуда), опциональный сброс устройств и сообщение пользователю."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cabinet import admin_routes
from app.cabinet.admin_deps import require_admin
from app.cabinet.app import create_app
from app.cabinet.deps import get_db
from app.database.models import Subscription, User
from app.external.remnawave.base import RemnawaveUser
from app.external.remnawave.mock import MockRemnawaveClient
from app.external.remnawave.real import RealRemnawaveClient
from app.services import notification_service as ns
from tests.helpers import make_tariff, make_user

OLD_URL, OLD_SHORT = 'https://sub.example/old', 'oldshort'
NEW_URL, NEW_SHORT = 'https://sub.example/new', 'newshort'
TELEGRAM_ID = 101
PATH = '/cabinet/admin/users/{}/revoke-subscription'


async def _seed(factory, *, remnawave_uuid: str | None = '7', with_subscription: bool = True) -> int:
    user_id = await make_user(factory, telegram_id=TELEGRAM_ID, remnawave_uuid=remnawave_uuid)
    if with_subscription:
        tariff_id = await make_tariff(factory)
        async with factory() as db:
            db.add(Subscription(
                user_id=user_id, tariff_id=tariff_id, status='active', end_date=datetime.now(timezone.utc) + timedelta(days=10),
                subscription_url=OLD_URL, short_uuid=OLD_SHORT,
            ))
            await db.commit()
    return user_id


async def _subscription(factory, user_id: int) -> Subscription:
    async with factory() as db:
        return (await db.execute(select(Subscription).where(Subscription.user_id == user_id))).scalar_one()


@pytest.fixture
def panel(monkeypatch):
    """Подмена клиента Remnawave: revoke возвращает новую ссылку, сброс устройств — успешный."""
    client = SimpleNamespace(
        revoke_user_subscription=AsyncMock(return_value=RemnawaveUser(uuid='7', subscription_url=NEW_URL, short_uuid=NEW_SHORT)),
        reset_user_devices=AsyncMock(),
    )
    monkeypatch.setattr(admin_routes, 'get_remnawave_client', lambda: client)
    return client


@pytest.fixture
def api(session_factory, panel):
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
        yield client


def _revoke(api, user_id: int, **body):
    return api.post(PATH.format(user_id), json=body)


def test_link_and_passwords_returns_the_new_link_and_stores_it_in_the_database(api, panel, session_factory):
    user_id = asyncio.run(_seed(session_factory))

    response = _revoke(api, user_id, mode='link_and_passwords', reset_devices=False, notify=False)

    assert response.status_code == 200
    assert response.json() == {'status': 'revoked', 'mode': 'link_and_passwords', 'subscription_url': NEW_URL}
    panel.revoke_user_subscription.assert_awaited_once_with(remnawave_uuid='7', revoke_only_passwords=False)
    stored = asyncio.run(_subscription(session_factory, user_id))
    assert (stored.subscription_url, stored.short_uuid) == (NEW_URL, NEW_SHORT)


def test_passwords_only_keeps_the_link_and_returns_null(api, panel, session_factory):
    user_id = asyncio.run(_seed(session_factory))

    response = _revoke(api, user_id, mode='passwords_only', reset_devices=False, notify=False)

    assert response.status_code == 200
    assert response.json() == {'status': 'revoked', 'mode': 'passwords_only', 'subscription_url': None}
    panel.revoke_user_subscription.assert_awaited_once_with(remnawave_uuid='7', revoke_only_passwords=True)
    stored = asyncio.run(_subscription(session_factory, user_id))
    assert (stored.subscription_url, stored.short_uuid) == (OLD_URL, OLD_SHORT)


def test_flags_default_to_off_devices_are_kept_and_nobody_is_notified(api, panel, session_factory):
    user_id = asyncio.run(_seed(session_factory))

    assert _revoke(api, user_id, mode='link_and_passwords').status_code == 200

    panel.reset_user_devices.assert_not_awaited()
    api.bot.send_message.assert_not_awaited()


def test_reset_devices_flag_resets_devices_without_notifying(api, panel, session_factory):
    user_id = asyncio.run(_seed(session_factory))

    assert _revoke(api, user_id, mode='passwords_only', reset_devices=True, notify=False).status_code == 200

    panel.reset_user_devices.assert_awaited_once_with(remnawave_uuid='7')
    api.bot.send_message.assert_not_awaited()


def test_notify_flag_sends_the_editable_message_without_resetting_devices(api, panel, session_factory):
    user_id = asyncio.run(_seed(session_factory))

    assert _revoke(api, user_id, mode='link_and_passwords', reset_devices=False, notify=True).status_code == 200

    panel.reset_user_devices.assert_not_awaited()
    kwargs = api.bot.send_message.await_args.kwargs
    assert kwargs['chat_id'] == TELEGRAM_ID
    assert kwargs['text'] == '🔐 Ваш доступ к VPN обновлён. Откройте «Моя подписка», возьмите актуальную ссылку и обновите подписку в приложении.'


@pytest.mark.parametrize('seed', [dict(remnawave_uuid=None), dict(with_subscription=False)], ids=['no_remnawave_uuid', 'no_subscription'])
def test_missing_remnawave_uuid_or_subscription_is_404_and_the_panel_is_not_touched(api, panel, session_factory, seed):
    user_id = asyncio.run(_seed(session_factory, **seed))

    response = _revoke(api, user_id, mode='link_and_passwords')

    assert response.status_code == 404
    assert response.json()['detail'] in ('У пользователя нет remnawave_uuid', 'У пользователя нет подписки в БД')
    panel.revoke_user_subscription.assert_not_awaited()


def test_unknown_user_is_404(api):
    response = _revoke(api, 999999, mode='link_and_passwords')

    assert (response.status_code, response.json()['detail']) == (404, 'Пользователь не найден')


@pytest.mark.parametrize('body', [dict(mode='everything'), dict(reset_devices=True), dict()], ids=['bad_mode', 'no_mode', 'empty'])
def test_mode_is_required_and_validated(api, panel, session_factory, body):
    user_id = asyncio.run(_seed(session_factory))

    assert api.post(PATH.format(user_id), json=body).status_code == 422
    panel.revoke_user_subscription.assert_not_awaited()


def test_panel_failure_is_502_and_changes_nothing(api, panel, session_factory):
    user_id = asyncio.run(_seed(session_factory))
    panel.revoke_user_subscription.side_effect = RuntimeError('panel down')

    response = _revoke(api, user_id, mode='link_and_passwords', reset_devices=True, notify=True)

    assert response.status_code == 502
    stored = asyncio.run(_subscription(session_factory, user_id))
    assert (stored.subscription_url, stored.short_uuid) == (OLD_URL, OLD_SHORT)
    panel.reset_user_devices.assert_not_awaited()
    api.bot.send_message.assert_not_awaited()


def test_panel_answer_without_a_link_never_blanks_the_stored_link(api, panel, session_factory):
    user_id = asyncio.run(_seed(session_factory))
    panel.revoke_user_subscription.return_value = RemnawaveUser(uuid='7', subscription_url='', short_uuid='')

    response = _revoke(api, user_id, mode='link_and_passwords')

    assert response.status_code == 502
    stored = asyncio.run(_subscription(session_factory, user_id))
    assert (stored.subscription_url, stored.short_uuid) == (OLD_URL, OLD_SHORT)


def test_devices_reset_failure_after_a_successful_revoke_is_502_but_the_new_link_is_kept_and_user_is_told(api, panel, session_factory):
    user_id = asyncio.run(_seed(session_factory))
    panel.reset_user_devices.side_effect = RuntimeError('panel down')

    response = _revoke(api, user_id, mode='link_and_passwords', reset_devices=True, notify=True)

    assert response.status_code == 502
    assert 'повторите сброс' in response.json()['detail']
    stored = asyncio.run(_subscription(session_factory, user_id))
    assert (stored.subscription_url, stored.short_uuid) == (NEW_URL, NEW_SHORT)  # revoke уже не откатить
    api.bot.send_message.assert_awaited_once()  # доступ у пользователя уже изменился


def test_admin_is_required():
    with TestClient(create_app(AsyncMock())) as client:
        assert client.post(PATH.format(1), json={'mode': 'link_and_passwords'}).status_code == 401


# --- клиенты Remnawave -----------------------------------------------------------------------------------------------


def _real_client() -> tuple[RealRemnawaveClient, AsyncMock]:
    client = RealRemnawaveClient('http://panel', 'key')
    request = AsyncMock(return_value={'id': 7, 'shortUuid': NEW_SHORT, 'subscriptionUrl': NEW_URL, 'status': 'ACTIVE'})
    client._request = request  # type: ignore[method-assign]
    return client, request


def test_real_client_default_revoke_sends_no_body_exactly_as_before():
    client, request = _real_client()

    user = asyncio.run(client.revoke_user_subscription(remnawave_uuid='7'))

    request.assert_awaited_once_with('POST', '/users/7/actions/revoke')
    assert (user.subscription_url, user.short_uuid) == (NEW_URL, NEW_SHORT)


def test_real_client_passwords_only_sends_revoke_only_passwords():
    client, request = _real_client()

    asyncio.run(client.revoke_user_subscription(remnawave_uuid='7', revoke_only_passwords=True))

    request.assert_awaited_once_with('POST', '/users/7/actions/revoke', json_data={'revokeOnlyPasswords': True})


def _mock_user(client: MockRemnawaveClient) -> RemnawaveUser:
    return asyncio.run(client.create_user(
        telegram_id=1, squad_uuids=[], traffic_limit_gb=0, expire_at=datetime.now(timezone.utc) + timedelta(days=5)
    ))


def test_mock_client_rotates_the_link_only_in_link_mode():
    client = MockRemnawaveClient()
    user = _mock_user(client)
    before = (user.subscription_url, user.short_uuid)

    kept = asyncio.run(client.revoke_user_subscription(remnawave_uuid=user.uuid, revoke_only_passwords=True))
    assert (kept.subscription_url, kept.short_uuid) == before

    rotated = asyncio.run(client.revoke_user_subscription(remnawave_uuid=user.uuid))
    assert (rotated.subscription_url, rotated.short_uuid) != before


# --- сообщение ---------------------------------------------------------------------------------------------------------


def test_notify_subscription_revoked_uses_the_registered_event():
    bot = AsyncMock()

    asyncio.run(ns.notify_subscription_revoked(bot, telegram_id=TELEGRAM_ID))

    assert bot.send_message.await_args.kwargs['text'].startswith('🔐 Ваш доступ к VPN обновлён.')
