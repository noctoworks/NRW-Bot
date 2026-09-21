"""Безопасность платёжных вебхуков и доступа к админке кабинета.

Вебхуки гоняются через FastAPI TestClient. Тестовая БД — та же файловая SQLite,
что и у session_factory (для наполнения/проверок), но с отдельным engine внутри
event loop клиента."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cabinet.admin_deps import require_admin
from app.cabinet.app import create_app
from app.cabinet.deps import get_db
from app.config import settings
from app.database.models import Payment, Subscription, Transaction, User
from app.services.payment.cispay import CisPayProvider
from app.services.payment.platega import PlategaProvider
from tests.helpers import make_tariff, make_user

MERCHANT = 'merchant-1'
SECRET = 'platega-secret'
CISPAY_KEY = 'cispay-key'


@pytest.fixture
def client(session_factory):
    engine = create_async_engine(str(session_factory.kw['bind'].url), connect_args={'timeout': 30})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app = create_app(AsyncMock())
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(settings, 'PAYMENTS_MODE', 'real')
    monkeypatch.setattr(settings, 'PLATEGA_MERCHANT_ID', MERCHANT)
    monkeypatch.setattr(settings, 'PLATEGA_SECRET_KEY', SECRET)
    monkeypatch.setattr(settings, 'CISPAY_API_KEY', CISPAY_KEY)


async def _pending_payment(factory, provider: str) -> int:
    user_id = await make_user(factory)
    tariff_id = await make_tariff(factory)
    async with factory() as db:
        transaction = Transaction(user_id=user_id, type='subscription_payment', amount_kopeks=10000, status='pending')
        db.add(transaction)
        await db.flush()
        payment = Payment(
            user_id=user_id,
            transaction_id=transaction.id,
            provider=provider,
            external_id='ext-1',
            amount_kopeks=10000,
            status='pending',
            raw_payload={'kind': 'subscription', 'tariff_id': tariff_id, 'period_days': 30},
        )
        db.add(payment)
        await db.commit()
        return payment.id


async def _payment_status(factory, payment_id: int) -> str:
    async with factory() as db:
        return (await db.get(Payment, payment_id)).status


def _platega_headers(**overrides) -> dict:
    return {'X-MerchantId': MERCHANT, 'X-Secret': SECRET, **overrides}


def _cispay_request(body: dict, key: str = CISPAY_KEY) -> dict:
    raw = json.dumps(body).encode()
    signature = hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
    return {'content': raw, 'headers': {'X-Signature': signature, 'Content-Type': 'application/json'}}


# --- stub-режим: вебхуки закрыты ---------------------------------------------


@pytest.mark.parametrize('path', ['/platega-webhook', '/cispay-webhook'])
def test_webhooks_are_closed_in_stub_mode(session_factory, client, path):
    payment_id = asyncio.run(_pending_payment(session_factory, 'platega' if 'platega' in path else 'cispay'))

    response = client.post(path, json={'id': 'ext-1', 'status': 'CONFIRMED'})

    assert response.status_code == 503
    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'pending'


# --- пустые секреты -----------------------------------------------------------


def test_platega_rejects_empty_secrets_matching_empty_headers(monkeypatch):
    monkeypatch.setattr(settings, 'PLATEGA_MERCHANT_ID', '')
    monkeypatch.setattr(settings, 'PLATEGA_SECRET_KEY', '')

    verified = asyncio.run(PlategaProvider().verify_webhook({}, {'x-merchantid': '', 'x-secret': ''}))

    assert verified is False


def test_cispay_rejects_signature_made_with_empty_key(monkeypatch):
    monkeypatch.setattr(settings, 'CISPAY_API_KEY', '')
    raw = b'{"id": "ext-1", "status": "paid"}'
    signature = hmac.new(b'', raw, hashlib.sha256).hexdigest()

    verified = asyncio.run(CisPayProvider().verify_webhook({}, {'x-signature': signature}, raw_body=raw))

    assert verified is False


def test_platega_webhook_without_credentials_is_unauthorized(session_factory, client, real_mode, monkeypatch):
    monkeypatch.setattr(settings, 'PLATEGA_MERCHANT_ID', '')
    monkeypatch.setattr(settings, 'PLATEGA_SECRET_KEY', '')
    payment_id = asyncio.run(_pending_payment(session_factory, 'platega'))

    response = client.post('/platega-webhook', json={'id': 'ext-1', 'status': 'CONFIRMED'})

    assert response.status_code == 401
    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'pending'


def test_platega_wrong_secret_is_unauthorized(session_factory, client, real_mode):
    payment_id = asyncio.run(_pending_payment(session_factory, 'platega'))

    response = client.post(
        '/platega-webhook', json={'id': 'ext-1', 'status': 'CONFIRMED'}, headers=_platega_headers(**{'X-Secret': 'nope'})
    )

    assert response.status_code == 401
    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'pending'


def test_platega_verification_ping_still_works(client, real_mode):
    assert client.post('/platega-webhook').status_code == 200


# --- подтверждение статуса у провайдера ---------------------------------------


def test_platega_webhook_claiming_success_is_not_trusted(session_factory, client, real_mode, monkeypatch):
    """Верные заголовки, но сам провайдер говорит, что платёж не оплачен."""
    monkeypatch.setattr(PlategaProvider, 'check_payment_status', AsyncMock(return_value='pending'))
    payment_id = asyncio.run(_pending_payment(session_factory, 'platega'))

    response = client.post('/platega-webhook', json={'id': 'ext-1', 'status': 'CONFIRMED'}, headers=_platega_headers())

    assert response.status_code == 200
    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'pending'


def test_platega_webhook_confirmed_by_provider_finalizes(session_factory, client, real_mode, monkeypatch):
    check = AsyncMock(return_value='success')
    monkeypatch.setattr(PlategaProvider, 'check_payment_status', check)
    payment_id = asyncio.run(_pending_payment(session_factory, 'platega'))

    response = client.post('/platega-webhook', json={'id': 'ext-1', 'status': 'CONFIRMED'}, headers=_platega_headers())

    assert response.status_code == 200
    check.assert_awaited_once_with('ext-1', amount_kopeks=10000)
    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'success'

    async def subscriptions() -> int:
        async with session_factory() as db:
            return len((await db.execute(Subscription.__table__.select())).all())

    assert asyncio.run(subscriptions()) == 1


def test_platega_webhook_when_provider_unreachable_returns_400_and_keeps_pending(
    session_factory, client, real_mode, monkeypatch
):
    monkeypatch.setattr(PlategaProvider, 'check_payment_status', AsyncMock(side_effect=RuntimeError('timeout')))
    payment_id = asyncio.run(_pending_payment(session_factory, 'platega'))

    response = client.post('/platega-webhook', json={'id': 'ext-1', 'status': 'CONFIRMED'}, headers=_platega_headers())

    assert response.status_code == 400
    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'pending'


def test_failed_webhook_is_also_confirmed_with_provider(session_factory, client, real_mode, monkeypatch):
    """Поддельный 'failed' не должен гасить платёж, который у провайдера ещё жив."""
    monkeypatch.setattr(PlategaProvider, 'check_payment_status', AsyncMock(return_value='pending'))
    payment_id = asyncio.run(_pending_payment(session_factory, 'platega'))

    client.post('/platega-webhook', json={'id': 'ext-1', 'status': 'CANCELED'}, headers=_platega_headers())

    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'pending'


def test_cispay_valid_signature_but_provider_says_pending(session_factory, client, real_mode, monkeypatch):
    monkeypatch.setattr(CisPayProvider, 'check_payment_status', AsyncMock(return_value='pending'))
    payment_id = asyncio.run(_pending_payment(session_factory, 'cispay'))

    response = client.post('/cispay-webhook', **_cispay_request({'id': 'ext-1', 'status': 'paid'}))

    assert response.status_code == 200
    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'pending'


def test_cispay_bad_signature_is_unauthorized(session_factory, client, real_mode):
    payment_id = asyncio.run(_pending_payment(session_factory, 'cispay'))

    response = client.post('/cispay-webhook', **_cispay_request({'id': 'ext-1', 'status': 'paid'}, key='wrong'))

    assert response.status_code == 401
    assert asyncio.run(_payment_status(session_factory, payment_id)) == 'pending'


# --- доступ к веб-админке ------------------------------------------------------


def test_admin_flag_in_db_alone_is_not_enough(monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_TELEGRAM_IDS', '111')
    removed_admin = User(telegram_id=222, referral_code='x', is_admin=True)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_admin(removed_admin))

    assert exc_info.value.status_code == 403


def test_admin_from_env_with_flag_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_TELEGRAM_IDS', '111,222')
    admin = User(telegram_id=222, referral_code='x', is_admin=True)

    assert asyncio.run(require_admin(admin)) is admin


def test_regular_user_is_forbidden(monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_TELEGRAM_IDS', '111')

    with pytest.raises(HTTPException):
        asyncio.run(require_admin(User(telegram_id=333, referral_code='x', is_admin=False)))
