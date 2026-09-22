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
    # Только фоновые задачи рассылки (start_broadcast именует их 'broadcast-{id}') — портал
    # TestClient держит собственную задачу lifespan всё время жизни клиента, её ждать нельзя.
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and (t.get_name() or '').startswith('broadcast-')]
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

    api.portal.call(_await_background_tasks)
    api.bot.send_message.assert_awaited_once()


def test_create_rejects_when_already_running(api):
    api.post(BASE + '/', json={'target': 'all', 'text': 'Первая'})
    response = api.post(BASE + '/', json={'target': 'all', 'text': 'Вторая'})
    assert response.status_code == 409

    api.portal.call(_await_background_tasks)


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

    api.portal.call(_await_background_tasks)

    response = api.get(f'{BASE}/{broadcast_id}')
    assert response.status_code == 200
    assert response.json()['status'] == 'completed'
    assert response.json()['sent_count'] == 1


def test_list_returns_history_with_pagination_fields(api):
    api.post(BASE + '/', json={'target': 'all', 'text': 'В историю'})

    api.portal.call(_await_background_tasks)

    response = api.get(BASE + '/')
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 1
    assert body['page'] == 1
    assert body['items'][0]['target_display_name'] == '👥 Всем'


def test_cancel_unknown_broadcast_returns_404(api):
    response = api.post(f'{BASE}/999999/cancel')
    assert response.status_code == 404


def test_cancel_stops_before_sending(api, session_factory):
    # 30 получателей => 2 пачки (BATCH_SIZE=25): первая пачка успевает уйти до того, как отмена
    # дойдёт до фоновой задачи (единственный процесс, никакого реального сетевого ожидания на
    # send), а вот вторую пачку (после паузы BATCH_DELAY между пачками) отмена уже перехватывает
    # — состояние гонки на одном получателе непроверяемо детерминированно, поэтому 30, а не 1.
    for i in range(29):
        asyncio.run(make_user(session_factory, telegram_id=1000 + i, username=f'u{i}'))

    create = api.post(BASE + '/', json={'target': 'all', 'text': 'Отмена через API'})
    broadcast_id = create.json()['id']
    assert create.json()['total_count'] == 30

    cancel = api.post(f'{BASE}/{broadcast_id}/cancel')
    assert cancel.status_code == 202

    api.portal.call(_await_background_tasks)

    response = api.get(f'{BASE}/{broadcast_id}')
    body = response.json()
    assert body['status'] == 'cancelled'
    assert 0 < body['sent_count'] < body['total_count']


def test_cancel_already_finished_returns_409(api):
    create = api.post(BASE + '/', json={'target': 'all', 'text': 'Уже готова'})
    broadcast_id = create.json()['id']

    api.portal.call(_await_background_tasks)

    response = api.post(f'{BASE}/{broadcast_id}/cancel')
    assert response.status_code == 409
