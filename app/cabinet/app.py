from __future__ import annotations

from aiogram import Bot
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.cabinet.admin_routes import router as admin_router
from app.cabinet.routes import router
from app.cabinet.webhooks import router as webhooks_router
from app.config import settings


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

    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(webhooks_router)

    @app.get('/health')
    async def health() -> dict[str, str]:
        return {'status': 'ok'}

    return app
