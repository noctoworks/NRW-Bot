"""Фабрика клиента: mock или real по REMNAWAVE_MODE. Весь остальной код зависит
только от RemnawaveClient (интерфейса), никогда напрямую от Mock/Real."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings
from app.external.remnawave.base import RemnawaveClient
from app.external.remnawave.mock import MockRemnawaveClient

if TYPE_CHECKING:
    from app.database.models import User


def remnawave_user_description(user: 'User') -> str:
    """Поле description панельного аккаунта — только для идентификации
    админом в UI Remnawave, см. диалог: "Bot User: @username, если нет —
    Name из Telegram"."""
    if user.username:
        return f'Bot User: @{user.username}'
    if user.full_name:
        return f'Bot User: {user.full_name}'
    return f'Bot User: id{user.telegram_id}'


def get_remnawave_client() -> RemnawaveClient:
    if settings.REMNAWAVE_MODE == 'mock':
        return MockRemnawaveClient()

    from app.external.remnawave.real import RealRemnawaveClient

    return RealRemnawaveClient(
        base_url=settings.REMNAWAVE_BASE_URL,
        api_key=settings.REMNAWAVE_API_KEY,
        panel_secret_param=settings.REMNAWAVE_PANEL_SECRET_PARAM,
    )
