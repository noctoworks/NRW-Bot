from __future__ import annotations

import re
import time
import uuid

from aiogram import Bot
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.cabinet.admin_routes import router as admin_router
from app.cabinet.routes import router
from app.cabinet.webhooks import router as webhooks_router
from app.config import settings
from app.logging_setup import bind_context, clear_context, get_logger

log = get_logger(__name__)

_REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
QUIET_PATHS = frozenset({'/health'})


def create_app(bot: Bot) -> FastAPI:
    app = FastAPI(title='Bedolaga Cabinet API', docs_url=None, redoc_url=None)
    app.state.bot = bot

    origins = [o.strip() for o in settings.CABINET_ALLOWED_ORIGINS.split(',') if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=['*'],
            allow_headers=['*'],
        )

    @app.middleware('http')
    async def log_requests(request: Request, call_next):
        """Одна строка на запрос (метод, путь, статус, время, user_id) + request_id в
        контексте всех логов внутри обработки и в заголовке ответа. Query-строка не
        логируется (там могут быть токены)."""
        incoming = request.headers.get('x-request-id', '')
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex[:12]
        clear_context()
        bind_context(request_id=request_id, method=request.method, path=request.url.path)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception('http_request_failed', duration_ms=round((time.perf_counter() - started) * 1000))
            raise
        fields = {
            'status': response.status_code,
            'duration_ms': round((time.perf_counter() - started) * 1000),
            'user_id': getattr(request.state, 'user_id', None),
        }
        if request.url.path in QUIET_PATHS:
            log.debug('http_request', **fields)
        elif response.status_code >= 500:
            log.error('http_request', **fields)
        else:
            log.info('http_request', **fields)
        response.headers['X-Request-ID'] = request_id
        return response

    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(webhooks_router)

    @app.get('/health')
    async def health() -> dict[str, str]:
        return {'status': 'ok'}

    return app
