"""Фабрика клиента: mock или real по REMNAWAVE_MODE. Весь остальной код зависит
только от RemnawaveClient (интерфейса), никогда напрямую от Mock/Real."""

from __future__ import annotations

from app.config import settings
from app.external.remnawave.base import RemnawaveClient
from app.external.remnawave.mock import MockRemnawaveClient


def get_remnawave_client() -> RemnawaveClient:
    if settings.REMNAWAVE_MODE == 'mock':
        return MockRemnawaveClient()

    from app.external.remnawave.real import RealRemnawaveClient

    return RealRemnawaveClient(base_url=settings.REMNAWAVE_BASE_URL, api_key=settings.REMNAWAVE_API_KEY)
