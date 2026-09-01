"""Боевой Remnawave-клиент (REMNAWAVE_MODE=real).

Эндпоинты/поля сверены построчно с исходниками бэкенда панели
(github.com/remnawave/backend, ветка main, актуально на релиз 3.2.3 /
2026-08-10 — см. диалог "docs.rw/api изучи там недавно были обновления").

ВАЖНО (это меняли предыдущий агент по ошибке — не возвращать обратно):
коммитом "refactor: replace all users routes to use id instaed of uuid"
(2026-07-13, уже в стабильных релизах) панель перешла с UUID на числовой
внутренний `id` для ВСЕХ users-экшенов (/users/{id}/actions/..., GET
/users/{id}) и для HWID-устройств (вынесены в отдельный контроллер
/hwid/devices/..., адресуются numeric userId). Поля `uuid` в ответе
пользователя больше нет вообще (UsersSchema: только `id: number` +
`shortUuid`). RemnawaveClient (base.py) по-прежнему держит контракт
remnawave_uuid: str — это НЕ настоящий UUID, а str(id) панели; менять
интерфейс/имя поля в БД не нужно, он используется просто как непрозрачный
идентификатор везде, кроме этого файла.

Не изменилось: POST /users (create), PATCH /users (update; тело — id ИЛИ
username, не uuid), GET /users/by-username/{username}, GET /internal-squads
(это по-прежнему честный uuid), статусы ACTIVE/DISABLED/LIMITED/EXPIRED,
код ошибки A019.

Базовый URL: SDK автоматически добавляет префикс /api — здесь то же самое,
явно в _request().
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.external.remnawave.base import (
    RemnawaveClient,
    RemnawaveDevice,
    RemnawaveUser,
    SubscriptionPageApp,
    SubscriptionPageBlock,
    SubscriptionPageButton,
    SubscriptionPageConfig,
    SubscriptionPagePlatform,
)

logger = logging.getLogger(__name__)

# Конфиг Subpage Builder одинаков для всех пользователей и меняется редко
# (админ правит его в самой панели) — кэшируем на уровне модуля (не инстанса:
# get_remnawave_client() создаёт новый RealRemnawaveClient на каждый вызов),
# чтобы не ходить в Remnawave по два запроса (список конфигов + конфиг по uuid)
# на каждое открытие экрана подключения.
_SUBPAGE_CONFIG_TTL_SECONDS = 600
_subpage_config_cache: dict[str, tuple[float, SubscriptionPageConfig | None]] = {}


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
            # Без этих трёх панель молча рвёт ЛЮБОЙ запрос без ответа —
            # ProxyCheckMiddleware требует доказательства, что запрос пришёл
            # через HTTPS-реверс-прокси, даже для внутреннего docker-трафика
            # (найдено вживую, 2026-08-20: даже list_internal_squads падал
            # httpx.RemoteProtocolError на каждой попытке). Значения и сам
            # факт требования — портировано из оригинального бота
            # (app/external/remnawave_api.py::_prepare_auth_headers).
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-For': '127.0.0.1',
            'X-Real-IP': '127.0.0.1',
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
        # usedTrafficBytes переехал в userTraffic.usedTrafficBytes (было плоским полем).
        used_traffic_bytes = int((data.get('userTraffic') or {}).get('usedTrafficBytes') or 0)
        return RemnawaveUser(
            uuid=str(data['id']),
            subscription_url=data.get('subscriptionUrl') or '',
            short_uuid=data.get('shortUuid') or '',
            traffic_used_gb=used_traffic_bytes / 1024**3,
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
        self,
        *,
        telegram_id: int,
        squad_uuids: list[str],
        traffic_limit_gb: int,
        expire_at: datetime,
        description: str | None = None,
    ) -> RemnawaveUser:
        username = f'tg{telegram_id}'
        body: dict[str, Any] = {
            'username': username,
            'status': 'ACTIVE',
            'expireAt': expire_at.isoformat(),
            'trafficLimitBytes': traffic_limit_gb * 1024**3,
            'trafficLimitStrategy': 'NO_RESET',
            'telegramId': telegram_id,
            'activeInternalSquads': squad_uuids,
        }
        if description:
            # CreateUserBodyDto.description — optional, но НЕ nullable: явный
            # null в теле не пройдёт валидацию, поэтому ключ либо есть, либо его нет.
            body['description'] = description
        try:
            data = await self._request('POST', '/users', json_data=body)
        except RuntimeError as error:
            # A019 "User username already exists" — наша сторона (User.remnawave_uuid)
            # потеряла связь с уже существующим панельным аккаунтом (например, локальную
            # запись удалили/сбросили и завели заново — см. диалог, живой случай на
            # тесте), а сам аккаунт в Remnawave остался. Переиспользуем его вместо
            # падения: находим по username, приводим лимиты/срок к запрошенным.
            if 'A019' not in str(error):
                raise
            logger.warning('Remnawave: username %s уже существует — переиспользую существующий аккаунт', username)
            existing = await self._request('GET', f'/users/by-username/{username}')
            patch_body: dict[str, Any] = {
                'id': existing['id'],
                'status': 'ACTIVE',
                'expireAt': expire_at.isoformat(),
                'trafficLimitBytes': traffic_limit_gb * 1024**3,
                'activeInternalSquads': squad_uuids,
            }
            if description:
                patch_body['description'] = description
            data = await self._request('PATCH', '/users', json_data=patch_body)
        return self._parse_user(data)

    async def extend_user_expiration(
        self,
        *,
        remnawave_uuid: str,
        expire_at: datetime,
        traffic_limit_gb: int | None = None,
        squad_uuids: list[str] | None = None,
    ) -> RemnawaveUser:
        patch_body: dict[str, Any] = {'id': int(remnawave_uuid), 'expireAt': expire_at.isoformat()}
        if traffic_limit_gb is not None:
            patch_body['trafficLimitBytes'] = traffic_limit_gb * 1024**3
        if squad_uuids is not None:
            patch_body['activeInternalSquads'] = squad_uuids
        data = await self._request('PATCH', '/users', json_data=patch_body)
        return self._parse_user(data)

    async def enable_user(self, *, remnawave_uuid: str) -> None:
        # A030 "User already enabled" — панель считает повторный enable ошибкой,
        # а не идемпотентной операцией. Вызывающий код (subscription_provisioning.py,
        # handlers/subscription.py, cabinet/admin_routes.py::adjust_subscription_days)
        # безусловно шлёт enable после ЛЮБОГО продления, включая продление ещё
        # активной (не отключённой) подписки — это основной, самый частый случай.
        # Без этого перехвата такое продление 500-ит целиком, хотя сама дата
        # окончания уже успешно обновлена строкой выше по стеку. Найдено вживую
        # при добавлении adjust_subscription_days (см. диалог).
        try:
            await self._request('POST', f'/users/{remnawave_uuid}/actions/enable')
        except RuntimeError as error:
            if 'A030' not in str(error):
                raise

    async def disable_user(self, *, remnawave_uuid: str) -> None:
        # Не применяю тот же перехват, что у enable_user — реальный errorCode для
        # "уже отключён" не подтверждён вживую (в отличие от A030 у enable),
        # гадать не стал. Если всплывёт та же проблема — искать код в тексте
        # ошибки и добавить сюда по аналогии.
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
        data = await self._request('GET', f'/hwid/devices/{remnawave_uuid}')
        devices = data.get('devices', []) if isinstance(data, dict) else (data or [])
        return [self._parse_device(d) for d in devices]

    async def reset_user_devices(self, *, remnawave_uuid: str) -> None:
        await self._request('POST', '/hwid/devices/delete-all', json_data={'userId': int(remnawave_uuid)})

    async def get_user_traffic_by_node(self, *, remnawave_uuid: str, days: int = 30) -> list[dict]:
        # Проверено вживую на тестовой панели (см. диалог 2026-09-01):
        # GET /bandwidth-stats/users/{id}.
        end = date.today()
        start = end - timedelta(days=days)
        data = await self._request(
            'GET',
            f'/bandwidth-stats/users/{remnawave_uuid}',
            params={'start': start.isoformat(), 'end': end.isoformat(), 'topNodesLimit': 20},
        )
        top_nodes = data.get('topNodes', []) if isinstance(data, dict) else []
        return [
            {
                'node_uuid': n['uuid'],
                'node_name': n.get('name', ''),
                'country_code': n.get('countryCode') or '',
                'total_bytes': int(n.get('total') or 0),
            }
            for n in top_nodes
        ]

    async def remove_device(self, *, remnawave_uuid: str, hwid: str) -> None:
        await self._request('POST', '/hwid/devices/delete', json_data={'userId': int(remnawave_uuid), 'hwid': hwid})

    async def list_internal_squads(self) -> list[dict]:
        data = await self._request('GET', '/internal-squads')
        squads = data.get('internalSquads', []) if isinstance(data, dict) else (data or [])
        return [{'uuid': s['uuid'], 'name': s.get('name', ''), 'country': ''} for s in squads]

    async def list_nodes(self) -> list[dict]:
        # Проверено вживую на тестовой панели (см. диалог 2026-09-01): GET /nodes
        # отдаёт голый массив (не {"nodes": [...]}), но на всякий случай — тот же
        # defensive-фоллбэк, что и в list_internal_squads выше, если формат
        # ответа отличается на другой версии панели. countryCode у части нод
        # реально приходит "XX" (не задан на панели) — не наша ошибка парсинга.
        data = await self._request('GET', '/nodes')
        nodes = data.get('nodes', []) if isinstance(data, dict) else (data or [])
        return [
            {
                'uuid': n['uuid'],
                'name': n.get('name', ''),
                'country_code': n.get('countryCode') or '',
                'is_connected': bool(n.get('isConnected')),
                'is_disabled': bool(n.get('isDisabled')),
                'traffic_used_gb': int(n.get('trafficUsedBytes') or 0) / 1024**3,
            }
            for n in nodes
        ]

    async def get_system_stats(self) -> dict:
        # Проверено вживую на тестовой панели (см. диалог 2026-09-01): GET /system/stats.
        data = await self._request('GET', '/system/stats')
        return {
            'cpu_cores': data['cpu']['cores'],
            'memory_used_bytes': data['memory']['used'],
            'memory_total_bytes': data['memory']['total'],
            'uptime_seconds': data['uptime'],
            'users_online_now': data['onlineStats']['onlineNow'],
            'users_online_last_day': data['onlineStats']['lastDay'],
            'users_online_last_week': data['onlineStats']['lastWeek'],
            'users_never_online': data['onlineStats']['neverOnline'],
            'nodes_online': data['nodes']['totalOnline'],
            'nodes_total_bytes_lifetime': int(data['nodes']['totalBytesLifetime']),
        }

    async def get_nodes_metrics(self) -> list[dict]:
        # Проверено вживую на тестовой панели (см. диалог 2026-09-01): GET /system/nodes/metrics.
        data = await self._request('GET', '/system/nodes/metrics')
        nodes = data.get('nodes', []) if isinstance(data, dict) else (data or [])
        return [
            {
                'node_uuid': n['nodeUuid'],
                'node_name': n.get('nodeName', ''),
                'users_online': n.get('usersOnline', 0),
                'inbound_stats': [
                    {'tag': s['tag'], 'upload': s['upload'], 'download': s['download']} for s in n.get('inboundsStats', [])
                ],
                'outbound_stats': [
                    {'tag': s['tag'], 'upload': s['upload'], 'download': s['download']} for s in n.get('outboundsStats', [])
                ],
            }
            for n in nodes
        ]

    async def get_subscription_page_config(self) -> SubscriptionPageConfig | None:
        # Эндпоинты сверены вживую с боевой панелью (см. диалог, 2026-08-19):
        # GET /api/subscription-page-configs -> {"total", "configs": [{"uuid","name","config": null}, ...]}
        # (список НЕ включает сам config — это оптимизация ответа на их стороне),
        # GET /api/subscription-page-configs/{uuid} -> {"uuid","name","config": {...}}
        # с полным Subpage Builder JSON (locales/platforms/apps/blocks/buttons).
        # На практике на панели всегда ровно один конфиг ("Default") — берём первый
        # по списку, а не хардкодим well-known uuid 00000000-0000-0000-0000-000000000000,
        # на случай если админ когда-нибудь заведёт несколько и сменит порядок.
        cache_key = self.base_url
        cached = _subpage_config_cache.get(cache_key)
        if cached is not None and time.monotonic() - cached[0] < _SUBPAGE_CONFIG_TTL_SECONDS:
            return cached[1]

        result: SubscriptionPageConfig | None = None
        try:
            listing = await self._request('GET', '/subscription-page-configs')
            configs = listing.get('configs') or [] if isinstance(listing, dict) else []
            if configs:
                detail = await self._request('GET', f"/subscription-page-configs/{configs[0]['uuid']}")
                raw_config = detail.get('config') if isinstance(detail, dict) else None
                if raw_config:
                    result = self._parse_subpage_config(raw_config)
        except Exception:
            logger.warning('Не удалось получить subscription-page-config панели', exc_info=True)

        _subpage_config_cache[cache_key] = (time.monotonic(), result)
        return result

    @staticmethod
    def _parse_subpage_config(raw: dict[str, Any]) -> SubscriptionPageConfig:
        platforms: list[SubscriptionPagePlatform] = []
        for key, platform_data in (raw.get('platforms') or {}).items():
            apps: list[SubscriptionPageApp] = []
            for app_data in platform_data.get('apps') or []:
                blocks: list[SubscriptionPageBlock] = []
                for block_data in app_data.get('blocks') or []:
                    buttons = [
                        SubscriptionPageButton(
                            type=button.get('type', ''),
                            link=button.get('link', ''),
                            text=button.get('text') or {},
                        )
                        for button in block_data.get('buttons') or []
                    ]
                    # Чисто текстовые шаги ("Предупреждение", "Если подписка не
                    # добавилась") — тоже часть таймлайна инструкции в Mini App
                    # (см. референс sub_page), не фильтруем по наличию кнопок.
                    blocks.append(
                        SubscriptionPageBlock(
                            title=block_data.get('title') or {},
                            description=block_data.get('description') or {},
                            icon_key=block_data.get('svgIconKey') or '',
                            icon_color=block_data.get('svgIconColor') or '',
                            buttons=buttons,
                        )
                    )
                apps.append(
                    SubscriptionPageApp(
                        name=app_data.get('name', ''),
                        featured=bool(app_data.get('featured')),
                        blocks=blocks,
                    )
                )
            platforms.append(
                SubscriptionPagePlatform(
                    key=key,
                    display_name=platform_data.get('displayName') or {},
                    apps=apps,
                )
            )
        return SubscriptionPageConfig(platforms=platforms)
