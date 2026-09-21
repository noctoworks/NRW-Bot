"""app/external/http.py — ретраи только там, где они безопасны."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.external import http


@pytest.fixture
def transport(monkeypatch):
    """Подменяет клиент на MockTransport; calls — список выполненных запросов,
    script — очередь ответов/исключений (по одному на запрос)."""

    class Scripted:
        def __init__(self) -> None:
            self.script: list = []
            self.calls: list[httpx.Request] = []

        def handler(self, request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            return httpx.Response(step)

    scripted = Scripted()
    monkeypatch.setattr(http, '_cached', None)
    monkeypatch.setattr(http, '_make_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(scripted.handler)))
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(http.asyncio, 'sleep', fake_sleep)
    scripted.sleeps = sleeps
    return scripted


def _send(method: str, **kwargs) -> httpx.Response:
    return asyncio.run(http.send_with_retry(method, 'https://example.test/x', **kwargs))


def test_get_retries_503_then_succeeds(transport):
    transport.script = [503, 503, 200]

    response = _send('GET')

    assert response.status_code == 200
    assert len(transport.calls) == 3
    assert transport.sleeps == [0.5, 1.0]  # экспоненциальная пауза


def test_get_returns_last_5xx_when_retries_exhausted(transport):
    transport.script = [503, 503, 503]

    assert _send('GET').status_code == 503
    assert len(transport.calls) == 3


def test_post_is_not_retried_on_503(transport):
    """Сервер мог уже выполнить запрос — повтор POST создал бы дубль."""
    transport.script = [503]

    assert _send('POST').status_code == 503
    assert len(transport.calls) == 1


def test_post_is_retried_on_connect_error(transport):
    """Соединения не было — запрос точно не выполнен, повторять безопасно."""
    transport.script = [httpx.ConnectError('refused'), 200]

    assert _send('POST').status_code == 200
    assert len(transport.calls) == 2


def test_get_is_retried_on_read_timeout(transport):
    transport.script = [httpx.ReadTimeout('slow'), 200]

    assert _send('GET').status_code == 200


def test_post_is_not_retried_on_read_timeout(transport):
    transport.script = [httpx.ReadTimeout('slow')]

    with pytest.raises(httpx.ReadTimeout):
        _send('POST')
    assert len(transport.calls) == 1


def test_explicit_idempotent_post_is_retried(transport):
    transport.script = [502, 200]

    assert _send('POST', idempotent=True).status_code == 200


def test_connect_error_is_raised_after_retries(transport):
    transport.script = [httpx.ConnectError('down')] * 3

    with pytest.raises(httpx.ConnectError):
        _send('GET')
    assert len(transport.calls) == 3


def test_client_error_is_not_retried(transport):
    transport.script = [404]

    assert _send('GET').status_code == 404
    assert len(transport.calls) == 1


def test_client_is_shared_within_loop_and_recreated_for_new_loop(monkeypatch):
    monkeypatch.setattr(http, '_cached', None)

    async def same_loop():
        return http.get_http_client() is http.get_http_client()

    async def grab():
        client = http.get_http_client()
        await http.close_http_client()
        return client

    assert asyncio.run(same_loop()) is True
    first = asyncio.run(grab())
    second = asyncio.run(grab())
    assert first is not second
