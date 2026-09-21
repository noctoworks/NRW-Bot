"""Единая настройка логирования на structlog.

Что даёт:
- один формат для ВСЕГО: и новые события (`log.info('payment_finalized', payment_id=1)`),
  и старые `logging.getLogger(...).info('... %s', x)`, и логи библиотек (aiogram,
  uvicorn, sqlalchemy) проходят через один конвейер;
- два вывода: цветной читаемый `console` (по умолчанию) и `json` (по строке на
  событие — для сбора в Loki/ELK/Datadog), переключается LOG_FORMAT;
- контекст запроса/апдейта (request_id, telegram_id, user_id, ...) автоматически
  попадает в каждую строку внутри обработки — через structlog.contextvars;
- маскирование секретов: токены/ключи из настроек, пароли в URL и токен бота
  вырезаются из любых строк (в т.ч. из traceback) до вывода;
- шум библиотек приглушён (httpx, aiogram.event, sqlalchemy.engine, ...).
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, Mapping
from typing import Any, TextIO

import structlog

REDACTED = '***'
_MIN_SECRET_LENGTH = 6  # короче — слишком велик риск замаскировать обычные слова

_TELEGRAM_TOKEN_RE = re.compile(r'\b\d{6,}:[A-Za-z0-9_-]{30,}\b')
_URL_CREDENTIALS_RE = re.compile(r'(?<=://)([^:/@\s]+):([^@\s]+)@')

# Библиотеки, которые на INFO/DEBUG засоряют вывод. Полезное о них мы логируем сами
# (LoggingMiddleware для апдейтов, HTTP-middleware для запросов).
_NOISY_LOGGERS: dict[str, int] = {
    'httpx': logging.WARNING,
    'httpcore': logging.WARNING,
    'aiogram.event': logging.WARNING,
    'aiogram.dispatcher': logging.WARNING,
    'sqlalchemy.engine': logging.WARNING,
    'aiosqlite': logging.WARNING,
    'asyncio': logging.WARNING,
    'uvicorn.access': logging.WARNING,
}


def build_redactor(secrets: Iterable[str]):
    """structlog-процессор: заменяет секреты и credentials в любых строковых
    значениях события (включая уже отформатированный traceback)."""
    secret_values = sorted({s for s in secrets if s and len(s) >= _MIN_SECRET_LENGTH}, key=len, reverse=True)

    def scrub(text: str) -> str:
        for secret in secret_values:
            text = text.replace(secret, REDACTED)
        text = _TELEGRAM_TOKEN_RE.sub(REDACTED, text)
        return _URL_CREDENTIALS_RE.sub(rf'\1:{REDACTED}@', text)

    def scrub_value(value: Any) -> Any:
        if isinstance(value, str):
            return scrub(value)
        if isinstance(value, Mapping):
            return {key: scrub_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(scrub_value(item) for item in value)
        return value

    def redact(logger: Any, method_name: str, event_dict: dict) -> dict:
        return {key: scrub_value(value) for key, value in event_dict.items()}

    return redact


def _settings_secrets() -> list[str]:
    from app.config import settings

    return [
        settings.BOT_TOKEN,
        settings.CABINET_JWT_SECRET,
        settings.REMNAWAVE_API_KEY,
        settings.REMNAWAVE_PANEL_SECRET_PARAM.partition('=')[2],
        settings.PLATEGA_SECRET_KEY,
        settings.CISPAY_API_KEY,
        settings.TONCENTER_API_KEY,
        settings.PROXY_SECRET,
    ]


def setup_logging(
    *,
    level: str = 'INFO',
    fmt: str = 'console',
    stream: TextIO | None = None,
    secrets: Iterable[str] | None = None,
) -> None:
    """Идемпотентна: повторный вызов заменяет предыдущую настройку. `secrets` по
    умолчанию берутся из настроек приложения (в тестах можно передать свои)."""
    json_output = fmt.lower() == 'json'
    stream = stream or sys.stdout
    colors = (not json_output) and hasattr(stream, 'isatty') and stream.isatty()

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt='iso' if json_output else '%Y-%m-%d %H:%M:%S', utc=json_output),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        build_redactor(_settings_secrets() if secrets is None else secrets),
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer(colors=colors, pad_event=32)
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    for name, noisy_level in _NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(max(noisy_level, root.level))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


bind_context = structlog.contextvars.bind_contextvars
clear_context = structlog.contextvars.clear_contextvars
