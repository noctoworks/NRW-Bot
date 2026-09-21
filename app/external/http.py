"""Общий HTTP-клиент для Remnawave и платёжных провайдеров.

Раньше каждый запрос создавал свой httpx.AsyncClient (новое TCP/TLS-соединение
на каждый вызов), имел один таймаут на 30 секунд и не повторял ничего при
сетевом сбое. Здесь:
- один клиент на event loop с пулом keep-alive соединений;
- раздельные таймауты: быстрое подключение (5с), разумное чтение;
- ретраи с экспоненциальной паузой, но только там, где это безопасно:
    * ConnectError/ConnectTimeout — запрос до сервера не дошёл, повторять можно
      для любого метода;
    * ReadTimeout/обрыв соединения/502-503-504 — сервер мог уже выполнить
      запрос, поэтому повторяем только идемпотентные (GET/HEAD/OPTIONS или
      явный idempotent=True), иначе получили бы двойное создание пользователя
      или платежа.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
RETRY_STATUSES = frozenset({502, 503, 504})
BACKOFF_BASE_SECONDS = 0.5
_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

# Клиент привязан к event loop, в котором создан (httpx/anyio не переживают
# смену loop) — при другом loop (скрипты, тесты) создаётся новый.
_cached: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )


def get_http_client() -> httpx.AsyncClient:
    global _cached
    loop = asyncio.get_running_loop()
    if _cached is None or _cached[0] is not loop or _cached[1].is_closed:
        _cached = (loop, _make_client())
    return _cached[1]


async def close_http_client() -> None:
    global _cached
    if _cached is not None:
        client = _cached[1]
        _cached = None
        if not client.is_closed:
            await client.aclose()


async def send_with_retry(
    method: str,
    url: str,
    *,
    retries: int = 2,
    idempotent: bool | None = None,
    timeout: float | httpx.Timeout | None = None,
    **kwargs,
) -> httpx.Response:
    """Как client.request, но с ретраями (см. докстринг модуля). Бросает
    httpx.HTTPError после исчерпания попыток; ответ с 5xx после исчерпания
    возвращается как есть — статус разбирает вызывающий код."""
    if idempotent is None:
        idempotent = method.upper() in _SAFE_METHODS
    if timeout is not None:
        kwargs['timeout'] = timeout

    client = get_http_client()
    attempt = 0
    while True:
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            retryable = True
            failure: httpx.HTTPError | None = error
        except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError) as error:
            retryable = idempotent
            failure = error
        else:
            if response.status_code in RETRY_STATUSES and idempotent and attempt < retries:
                logger.warning('%s %s -> %s, повтор %s/%s', method, url, response.status_code, attempt + 1, retries)
                await asyncio.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
                attempt += 1
                continue
            return response

        if not retryable or attempt >= retries:
            raise failure
        logger.warning('%s %s: %r, повтор %s/%s', method, url, failure, attempt + 1, retries)
        await asyncio.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
        attempt += 1
