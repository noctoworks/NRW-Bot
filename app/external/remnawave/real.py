"""Боевой Remnawave-клиент (REMNAWAVE_MODE=real).

Эндпоинты/поля сверены с официальной документацией панели (docs.rw, Remnawave
Python SDK reference — актуальная версия API на момент интеграции, см. диалог:
"docs.rw/api изучи там недавно были обновления") — НЕ с более старым
remnawave-bedolaga-telegram-bot/app/external/remnawave_api.py, который ключует
пользователей числовым internal id (/api/hwid/devices/{userId} и т.п.) —
там это устаревшая для нашей версии панели схема. Актуальная официальная схема
полностью UUID-based (/api/users/{uuid}, /api/users/{uuid}/hwid/...), что
дословно совпадает с уже зафиксированным контрактом RemnawaveClient
(remnawave_uuid: str везде) — адаптировать интерфейс под numeric id не
потребовалось.

Базовый URL: SDK автоматически добавляет префикс /api — здесь то же самое,
явно в _request().
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from app.external.remnawave.base import (
    RemnawaveClient,
    RemnawaveDevice,
    RemnawaveUser,
    SubscriptionPageConfig,
)

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class RealRemnawaveClient(RemnawaveClient):
    def __init__(self, base_url: str, api_key: str, panel_secret_param: str = '') -> None:
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        # "key=value" — см. REMNAWAVE_PANEL_SECRET_PARAM в app/config.py. Найдено
        # вживую: nginx перед панелью маскирует ВЕСЬ /, включая /api/*, за секретным
        # query/cookie-параметром (map $arg_<KEY> в его конфиге) — без него он рвёт
        # соединение без ответа (снаружи выглядит как Cloudflare 520, у нас как
        # httpx.RemoteProtocolError). Панель это не портит и не требует её трогать —
        # просто прикладываем параметр к каждому запросу.
        self._panel_secret_param: tuple[str, str] | None = None
        if panel_secret_param and '=' in panel_secret_param:
            key, _, value = panel_secret_param.partition('=')
            self._panel_secret_param = (key, value)

    def _headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    async def _request(
        self, method: str, path: str, *, json_data: dict[str, Any] | None = None, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f'{self.base_url}/api{path}'
        if self._panel_secret_param:
            key, value = self._panel_secret_param
            params = {**(params or {}), key: value}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, json=json_data, params=params, headers=self._headers())
        except httpx.HTTPError as error:
            logger.error('Remnawave request failed: %s %s — %s', method, path, error)
            raise RuntimeError(f'Remnawave недоступна: {error}') from error

        if response.status_code >= 400:
            logger.error('Remnawave API error %s on %s %s: %s', response.status_code, method, path, response.text)
            raise RuntimeError(f'Remnawave вернула ошибку {response.status_code}: {response.text[:200]}')

        if not response.text:
            return {}
        try:
            raw = response.json()
        except ValueError as error:
            raise RuntimeError(f'Remnawave вернула не-JSON ответ: {response.text[:200]}') from error

        return raw.get('response', raw) if isinstance(raw, dict) else raw

    def _parse_user(self, data: dict[str, Any]) -> RemnawaveUser:
        traffic_limit_bytes = int(data.get('trafficLimitBytes') or 0)
        return RemnawaveUser(
            uuid=data['uuid'],
            subscription_url=data.get('subscriptionUrl') or '',
            short_uuid=data.get('shortUuid') or '',
            traffic_used_gb=int(data.get('usedTrafficBytes') or 0) / 1024**3,
            traffic_limit_gb=traffic_limit_bytes // 1024**3,
            expire_at=_parse_dt(data.get('expireAt')),
            is_enabled=data.get('status') == 'ACTIVE',
        )

    def _parse_device(self, data: dict[str, Any]) -> RemnawaveDevice:
        return RemnawaveDevice(
            hwid=data.get('hwid') or '',
            platform=data.get('platform') or data.get('deviceOs') or '',
            device_model=data.get('deviceModel') or '',
            created_at=_parse_dt(data.get('createdAt')),
        )

    async def create_user(
        self, *, telegram_id: int, squad_uuids: list[str], traffic_limit_gb: int, expire_at: datetime
    ) -> RemnawaveUser:
        body = {
            'username': f'tg{telegram_id}',
            'status': 'ACTIVE',
            'expireAt': expire_at.isoformat(),
            'trafficLimitBytes': traffic_limit_gb * 1024**3,
            'trafficLimitStrategy': 'NO_RESET',
            'telegramId': telegram_id,
            'activeInternalSquads': squad_uuids,
        }
        data = await self._request('POST', '/users', json_data=body)
        return self._parse_user(data)

    async def extend_user_expiration(self, *, remnawave_uuid: str, expire_at: datetime) -> RemnawaveUser:
        data = await self._request('PATCH', '/users', json_data={'uuid': remnawave_uuid, 'expireAt': expire_at.isoformat()})
        return self._parse_user(data)

    async def enable_user(self, *, remnawave_uuid: str) -> None:
        await self._request('POST', f'/users/{remnawave_uuid}/actions/enable')

    async def disable_user(self, *, remnawave_uuid: str) -> None:
        await self._request('POST', f'/users/{remnawave_uuid}/actions/disable')

    async def revoke_user_subscription(self, *, remnawave_uuid: str) -> RemnawaveUser:
        data = await self._request('POST', f'/users/{remnawave_uuid}/actions/revoke')
        return self._parse_user(data)

    async def reset_user_traffic(self, *, remnawave_uuid: str) -> None:
        await self._request('POST', f'/users/{remnawave_uuid}/actions/reset-traffic')

    async def get_subscription_info(self, *, remnawave_uuid: str) -> RemnawaveUser:
        data = await self._request('GET', f'/users/{remnawave_uuid}')
        return self._parse_user(data)

    async def get_user_devices(self, *, remnawave_uuid: str) -> list[RemnawaveDevice]:
        data = await self._request('GET', f'/users/{remnawave_uuid}/hwid')
        devices = data.get('devices', []) if isinstance(data, dict) else (data or [])
        return [self._parse_device(d) for d in devices]

    async def reset_user_devices(self, *, remnawave_uuid: str) -> None:
        await self._request('DELETE', f'/users/{remnawave_uuid}/hwid')

    async def remove_device(self, *, remnawave_uuid: str, hwid: str) -> None:
        await self._request('DELETE', f'/users/{remnawave_uuid}/hwid/{hwid}')

    async def list_internal_squads(self) -> list[dict]:
        data = await self._request('GET', '/internal-squads')
        squads = data.get('internalSquads', []) if isinstance(data, dict) else (data or [])
        return [{'uuid': s['uuid'], 'name': s.get('name', ''), 'country': ''} for s in squads]

    async def get_subscription_page_config(self, uuid: str) -> SubscriptionPageConfig | None:
        # Не используется: список VPN-клиентов в Mini App захардкожен (см. диалог,
        # §8 clone-architecture.md отложен — "это часть Mini App, отдельный этап").
        return None
