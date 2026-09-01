"""Заглушка Remnawave для локальной разработки без боевой панели (см. диалог: REMNAWAVE_MODE=mock).

Состояние сохраняется на диск (mock_remnawave_state.json рядом с bot.db), а не
только в памяти процесса — иначе каждый перезапуск бота (обычное дело при
разработке — правки кода требуют рестарта) обнулял бы "VPN-панель", а в
SQLite-базе оставались бы User.remnawave_uuid, указывающие в никуда, с падением
LookupError при любом обращении к устройствам/подписке (баг, пойманный вживую
при тестировании — см. диалог).

Дополнительная подстраховка: если ссылка на пользователя всё же осталась битой
(например файл состояния вручную удалили, или подменили bot.db не тем файлом) —
_require_user САМОВОССТАНАВЛИВАЕТ запись вместо падения: создаёт нового
"теневого" mock-пользователя с тем же remnawave_uuid и дефолтными полями.
Это mock ИСКЛЮЧИТЕЛЬНО для локальной разработки — в реальном Remnawave-клиенте
(REMNAWAVE_MODE=real) такого самовосстановления, конечно, нет и не будет.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

_STATE_FILE = Path(__file__).resolve().parents[3] / 'mock_remnawave_state.json'

# Управление нодами (диалог 2026-09-01) — MockRemnawaveClient создаётся заново
# на каждый вызов get_remnawave_client() (см. комментарий в real.py), поэтому
# состояние "включена/выключена" держим на уровне модуля, не инстанса. В файл
# не сохраняем — это чисто dev-превью кнопок в админке, не переживать рестарт
# бота не страшно (в отличие от _STATE_FILE выше, где реальная потеря
# remnawave_uuid ломает пользователей).
_disabled_node_uuids: set[str] = set()


def _dt_to_str(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt_from_str(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class _State:
    users: dict[str, RemnawaveUser] = field(default_factory=dict)
    devices: dict[str, list[RemnawaveDevice]] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            'users': {
                uid: {**asdict(u), 'expire_at': _dt_to_str(u.expire_at)} for uid, u in self.users.items()
            },
            'devices': {
                uid: [{**asdict(d), 'created_at': _dt_to_str(d.created_at)} for d in devs]
                for uid, devs in self.devices.items()
            },
        }

    @classmethod
    def from_json(cls, data: dict) -> '_State':
        users = {
            uid: RemnawaveUser(**{**u, 'expire_at': _dt_from_str(u.get('expire_at'))})
            for uid, u in data.get('users', {}).items()
        }
        devices = {
            uid: [RemnawaveDevice(**{**d, 'created_at': _dt_from_str(d.get('created_at'))}) for d in devs]
            for uid, devs in data.get('devices', {}).items()
        }
        return cls(users=users, devices=devices)


def _load_state() -> _State:
    if not _STATE_FILE.exists():
        return _State()
    try:
        return _State.from_json(json.loads(_STATE_FILE.read_text(encoding='utf-8')))
    except Exception:
        logger.warning('Не удалось прочитать %s — начинаю с пустого состояния mock-Remnawave', _STATE_FILE, exc_info=True)
        return _State()


def _save_state(state: _State) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state.to_json(), ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        logger.warning('Не удалось сохранить %s', _STATE_FILE, exc_info=True)


class MockRemnawaveClient(RemnawaveClient):
    """Состояние общее для всех экземпляров процесса (загружается один раз на
    уровне класса) и переживает перезапуск процесса (сохраняется в файл)."""

    _state: _State = _load_state()

    async def create_user(
        self,
        *,
        telegram_id: int,
        squad_uuids: list[str],
        traffic_limit_gb: int,
        expire_at: datetime,
        description: str | None = None,
    ) -> RemnawaveUser:
        remnawave_uuid = str(uuid.uuid4())
        short_uuid = uuid.uuid4().hex[:12]
        user = RemnawaveUser(
            uuid=remnawave_uuid,
            subscription_url=f'https://mock.local/sub/{short_uuid}',
            short_uuid=short_uuid,
            traffic_used_gb=0.0,
            traffic_limit_gb=traffic_limit_gb,
            expire_at=expire_at,
            is_enabled=True,
        )
        self._state.users[remnawave_uuid] = user
        self._state.devices[remnawave_uuid] = []
        _save_state(self._state)
        return user

    async def extend_user_expiration(
        self,
        *,
        remnawave_uuid: str,
        expire_at: datetime,
        traffic_limit_gb: int | None = None,
        squad_uuids: list[str] | None = None,  # не моделируется в моке — RemnawaveUser сквады не хранит
    ) -> RemnawaveUser:
        user = self._require_user(remnawave_uuid)
        user.expire_at = expire_at
        if traffic_limit_gb is not None:
            user.traffic_limit_gb = traffic_limit_gb
        _save_state(self._state)
        return user

    async def enable_user(self, *, remnawave_uuid: str) -> None:
        self._require_user(remnawave_uuid).is_enabled = True
        _save_state(self._state)

    async def disable_user(self, *, remnawave_uuid: str) -> None:
        self._require_user(remnawave_uuid).is_enabled = False
        _save_state(self._state)

    async def revoke_user_subscription(self, *, remnawave_uuid: str) -> RemnawaveUser:
        user = self._require_user(remnawave_uuid)
        user.short_uuid = uuid.uuid4().hex[:12]
        user.subscription_url = f'https://mock.local/sub/{user.short_uuid}'
        _save_state(self._state)
        return user

    async def reset_user_traffic(self, *, remnawave_uuid: str) -> None:
        self._require_user(remnawave_uuid).traffic_used_gb = 0.0
        _save_state(self._state)

    async def get_subscription_info(self, *, remnawave_uuid: str) -> RemnawaveUser:
        return self._require_user(remnawave_uuid)

    async def get_user_devices(self, *, remnawave_uuid: str) -> list[RemnawaveDevice]:
        self._require_user(remnawave_uuid)
        return self._state.devices.get(remnawave_uuid, [])

    async def reset_user_devices(self, *, remnawave_uuid: str) -> None:
        self._require_user(remnawave_uuid)
        self._state.devices[remnawave_uuid] = []
        _save_state(self._state)

    async def remove_device(self, *, remnawave_uuid: str, hwid: str) -> None:
        self._require_user(remnawave_uuid)
        self._state.devices[remnawave_uuid] = [
            d for d in self._state.devices.get(remnawave_uuid, []) if d.hwid != hwid
        ]
        _save_state(self._state)

    async def get_user_traffic_by_node(self, *, remnawave_uuid: str, days: int = 30) -> list[dict]:
        # Формат полей — 1:1 с RealRemnawaveClient.get_user_traffic_by_node (см.
        # real.py, проверено вживую на тестовой панели). Реального разбиения по
        # нодам в моке нет — берём фактический traffic_used_gb юзера и делим
        # между двумя фикс-нодами (см. list_nodes выше), чтобы карточка юзера в
        # админке не была пустой на стенде (REMNAWAVE_MODE=mock).
        user = self._require_user(remnawave_uuid)
        total_bytes = int(user.traffic_used_gb * 1024**3)
        if total_bytes <= 0:
            return []
        return [
            {'node_uuid': 'mock-node-de', 'node_name': 'DE-01', 'country_code': 'DE', 'total_bytes': round(total_bytes * 0.7)},
            {'node_uuid': 'mock-node-fi', 'node_name': 'FI-01', 'country_code': 'FI', 'total_bytes': round(total_bytes * 0.3)},
        ]

    async def list_internal_squads(self) -> list[dict]:
        return [
            {'uuid': 'mock-squad-de', 'name': 'Germany', 'country': 'DE'},
            {'uuid': 'mock-squad-nl', 'name': 'Netherlands', 'country': 'NL'},
        ]

    async def list_nodes(self) -> list[dict]:
        # Staging/dev гоняют REMNAWAVE_MODE=mock (см. диалог 2026-09-01) — реальной
        # ноды тут нет физически, поэтому фикс-набор для превью раздела "Ноды" в
        # админке. Формат полей — 1:1 с RealRemnawaveClient.list_nodes (см. real.py,
        # проверено вживую на тестовой панели), только значения выдуманы.
        # is_disabled поверх фикс-набора — из _disabled_node_uuids, чтобы кнопки
        # вкл/выкл в админке реально что-то меняли даже в mock-режиме.
        nodes = [
            {'uuid': 'mock-node-de', 'name': 'DE-01', 'country_code': 'DE', 'is_connected': True, 'is_disabled': False, 'traffic_used_gb': 412.7},
            {'uuid': 'mock-node-fi', 'name': 'FI-01', 'country_code': 'FI', 'is_connected': True, 'is_disabled': False, 'traffic_used_gb': 198.3},
            {'uuid': 'mock-node-nl', 'name': 'NL-01', 'country_code': 'NL', 'is_connected': True, 'is_disabled': False, 'traffic_used_gb': 305.1},
            {'uuid': 'mock-node-se', 'name': 'SE-01', 'country_code': 'SE', 'is_connected': False, 'is_disabled': False, 'traffic_used_gb': 89.4},
        ]
        for node in nodes:
            node['is_disabled'] = node['uuid'] in _disabled_node_uuids
        return nodes

    async def enable_node(self, *, remnawave_uuid: str) -> dict:
        _disabled_node_uuids.discard(remnawave_uuid)
        return next(n for n in await self.list_nodes() if n['uuid'] == remnawave_uuid)

    async def disable_node(self, *, remnawave_uuid: str) -> dict:
        _disabled_node_uuids.add(remnawave_uuid)
        return next(n for n in await self.list_nodes() if n['uuid'] == remnawave_uuid)

    async def restart_node(self, *, remnawave_uuid: str) -> None:
        logger.info('Mock: restart_node(%s) — нет реальной ноды, ничего не делаем', remnawave_uuid)

    async def get_node_detail(self, *, remnawave_uuid: str) -> dict | None:
        # Формат — 1:1 с RealRemnawaveClient.get_node_detail (см. real.py),
        # значения выдуманы. system всегда None — как и на реальной ноде на
        # проде сейчас (диалог 2026-09-01: агент этого не репортит).
        nodes = await self.list_nodes()
        base = next((n for n in nodes if n['uuid'] == remnawave_uuid), None)
        if base is None:
            return None
        now = datetime.now(timezone.utc)
        return {
            **base,
            'address': f'{base["name"].lower()}.mock.local',
            'port': 2222,
            'is_connecting': False,
            'users_online': 12,
            'xray_uptime_seconds': 86_400.0,
            'last_status_change': now - timedelta(days=3),
            'last_status_message': None,
            'traffic_limit_gb': None,
            'traffic_reset_day': 1,
            'notify_percent': 80,
            'consumption_multiplier': 1.0,
            'tags': ['mock'],
            'note': None,
            'provider_name': None,
            'versions': {'xray': '26.7.28', 'node': '3.3.0'},
            'system': None,
            'created_at': now - timedelta(days=90),
            'updated_at': now,
        }

    async def get_system_stats(self) -> dict:
        # Формат полей — 1:1 с RealRemnawaveClient.get_system_stats (см. real.py,
        # проверено вживую на тестовой панели), значения выдуманы.
        return {
            'cpu_cores': 2,
            'memory_used_bytes': 1_200_000_000,
            'memory_total_bytes': 4_000_000_000,
            'uptime_seconds': 864_000.0,
            'users_online_now': 18,
            'users_online_last_day': 64,
            'users_online_last_week': 112,
            'users_never_online': 40,
            'nodes_online': 3,
            'nodes_total_bytes_lifetime': 1_200_000_000_000,
        }

    async def get_nodes_metrics(self) -> list[dict]:
        # Формат полей — 1:1 с RealRemnawaveClient.get_nodes_metrics (см. real.py,
        # проверено вживую на тестовой панели), значения выдуманы.
        return [
            {
                'node_uuid': 'mock-node-de',
                'node_name': 'DE-01',
                'users_online': 7,
                'inbound_stats': [{'tag': 'VLESS_SELFSTEAL_WITH_NGINX', 'upload': '412.30 MiB', 'download': '3.12 GiB'}],
                'outbound_stats': [{'tag': 'DIRECT', 'upload': '398.10 MiB', 'download': '3.05 GiB'}],
            },
            {
                'node_uuid': 'mock-node-fi',
                'node_name': 'FI-01',
                'users_online': 4,
                'inbound_stats': [{'tag': 'VLESS_SELFSTEAL_WITH_NGINX', 'upload': '201.50 MiB', 'download': '1.44 GiB'}],
                'outbound_stats': [{'tag': 'DIRECT', 'upload': '195.20 MiB', 'download': '1.40 GiB'}],
            },
            {
                'node_uuid': 'mock-node-nl',
                'node_name': 'NL-01',
                'users_online': 5,
                'inbound_stats': [{'tag': 'VLESS_SELFSTEAL_WITH_NGINX', 'upload': '305.80 MiB', 'download': '2.21 GiB'}],
                'outbound_stats': [{'tag': 'DIRECT', 'upload': '298.40 MiB', 'download': '2.18 GiB'}],
            },
        ]

    async def get_infra_billing(self) -> dict:
        # Формат полей — 1:1 с RealRemnawaveClient.get_infra_billing (см.
        # real.py, проверено вживую на тестовой панели), значения выдуманы —
        # на реальной тестовой панели сейчас 0 привязанных нод (никто ещё не
        # настроил Providers/Billing в самом Remnawave), но пустой мок не дал
        # бы проверить, как это вообще выглядит в UI.
        now = datetime.now(timezone.utc)
        return {
            'total_spent': 312.0,
            'current_month_payments': 78.0,
            'upcoming_nodes_count': 2,
            'nodes': [
                {'node_uuid': 'mock-node-de', 'node_name': 'DE-01', 'provider_name': 'Hetzner', 'next_billing_at': now + timedelta(days=12)},
                {'node_uuid': 'mock-node-fi', 'node_name': 'FI-01', 'provider_name': 'OVH', 'next_billing_at': now + timedelta(days=3)},
            ],
        }

    async def get_subscription_page_config(self) -> SubscriptionPageConfig | None:
        # Урезанная копия реального Subpage Builder боевой панели (см. диалог,
        # проверено вживую 2026-08-19) — только по одному приложению на платформу,
        # достаточно для разработки/превью Mini App без живой панели.
        def _happ_app(store_url: str, store_label: str) -> SubscriptionPageApp:
            return SubscriptionPageApp(
                name='Happ',
                featured=True,
                blocks=[
                    SubscriptionPageBlock(
                        title={'ru': 'Установка приложения', 'en': 'App installation'},
                        description={
                            'ru': 'Скачайте и установите приложение по кнопке ниже.',
                            'en': 'Download and install the app using the button below.',
                        },
                        icon_key='DownloadIcon',
                        icon_color='violet',
                        buttons=[
                            SubscriptionPageButton(
                                type='external', link=store_url, text={'ru': store_label, 'en': store_label}
                            )
                        ],
                    ),
                    SubscriptionPageBlock(
                        title={'ru': 'Добавление подписки', 'en': 'Add subscription'},
                        description={
                            'ru': 'Нажмите кнопку ниже, чтобы добавить подписку.',
                            'en': 'Tap the button below to add the subscription.',
                        },
                        icon_key='CloudDownload',
                        icon_color='cyan',
                        buttons=[
                            SubscriptionPageButton(
                                type='subscriptionLink',
                                link='happ://add/{{SUBSCRIPTION_LINK}}',
                                text={'ru': 'Добавить подписку', 'en': 'Add subscription'},
                            )
                        ],
                    ),
                    SubscriptionPageBlock(
                        title={'ru': 'Подключение и использование', 'en': 'Connect and use'},
                        description={
                            'ru': 'Включите VPN в приложении — готово.',
                            'en': 'Turn on the VPN in the app — done.',
                        },
                        icon_key='Check',
                        icon_color='teal',
                    ),
                ],
            )

        return SubscriptionPageConfig(
            platforms=[
                SubscriptionPagePlatform(
                    key='android',
                    display_name={'ru': 'Android', 'en': 'Android'},
                    apps=[_happ_app('https://play.google.com/store/apps/details?id=com.happproxy', 'Google Play')],
                ),
                SubscriptionPagePlatform(
                    key='ios',
                    display_name={'ru': 'iOS', 'en': 'iOS'},
                    apps=[_happ_app('https://apps.apple.com/us/app/happ-proxy-utility/id6504287215', 'App Store')],
                ),
                SubscriptionPagePlatform(
                    key='windows',
                    display_name={'ru': 'Windows', 'en': 'Windows'},
                    apps=[
                        _happ_app(
                            'https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe',
                            'GitHub',
                        )
                    ],
                ),
                SubscriptionPagePlatform(
                    key='macos',
                    display_name={'ru': 'macOS', 'en': 'macOS'},
                    apps=[_happ_app('https://apps.apple.com/us/app/happ-proxy-utility/id6504287215', 'App Store')],
                ),
            ]
        )

    def _require_user(self, remnawave_uuid: str) -> RemnawaveUser:
        user = self._state.users.get(remnawave_uuid)
        if user is None:
            logger.warning(
                'MockRemnawaveClient: %s отсутствует в состоянии — самовосстанавливаю '
                '"теневую" запись (файл состояния был удалён/подменён вручную?)',
                remnawave_uuid,
            )
            short_uuid = uuid.uuid4().hex[:12]
            user = RemnawaveUser(
                uuid=remnawave_uuid,
                subscription_url=f'https://mock.local/sub/{short_uuid}',
                short_uuid=short_uuid,
                traffic_used_gb=0.0,
                traffic_limit_gb=0,
                expire_at=None,
                is_enabled=True,
            )
            self._state.users[remnawave_uuid] = user
            self._state.devices.setdefault(remnawave_uuid, [])
            _save_state(self._state)
        return user
