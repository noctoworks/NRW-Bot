"""Заглушка Remnawave для локальной разработки без боевой панели (см. диалог: REMNAWAVE_MODE=mock).

Хранит состояние в памяти процесса — переживает только время жизни бота,
этого достаточно для разработки и ручного тестирования бизнес-логики.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.external.remnawave.base import (
    RemnawaveClient,
    RemnawaveDevice,
    RemnawaveUser,
    SubscriptionPageApp,
    SubscriptionPageConfig,
)


class MockRemnawaveClient(RemnawaveClient):
    _users: dict[str, RemnawaveUser] = {}
    _devices: dict[str, list[RemnawaveDevice]] = {}

    async def create_user(
        self, *, telegram_id: int, squad_uuids: list[str], traffic_limit_gb: int, expire_at: datetime
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
        self._users[remnawave_uuid] = user
        self._devices[remnawave_uuid] = []
        return user

    async def extend_user_expiration(self, *, remnawave_uuid: str, expire_at: datetime) -> RemnawaveUser:
        user = self._require_user(remnawave_uuid)
        user.expire_at = expire_at
        return user

    async def enable_user(self, *, remnawave_uuid: str) -> None:
        self._require_user(remnawave_uuid).is_enabled = True

    async def disable_user(self, *, remnawave_uuid: str) -> None:
        self._require_user(remnawave_uuid).is_enabled = False

    async def revoke_user_subscription(self, *, remnawave_uuid: str) -> RemnawaveUser:
        user = self._require_user(remnawave_uuid)
        user.short_uuid = uuid.uuid4().hex[:12]
        user.subscription_url = f'https://mock.local/sub/{user.short_uuid}'
        return user

    async def reset_user_traffic(self, *, remnawave_uuid: str) -> None:
        self._require_user(remnawave_uuid).traffic_used_gb = 0.0

    async def get_subscription_info(self, *, remnawave_uuid: str) -> RemnawaveUser:
        return self._require_user(remnawave_uuid)

    async def get_user_devices(self, *, remnawave_uuid: str) -> list[RemnawaveDevice]:
        self._require_user(remnawave_uuid)
        return self._devices.get(remnawave_uuid, [])

    async def reset_user_devices(self, *, remnawave_uuid: str) -> None:
        self._require_user(remnawave_uuid)
        self._devices[remnawave_uuid] = []

    async def remove_device(self, *, remnawave_uuid: str, hwid: str) -> None:
        self._require_user(remnawave_uuid)
        self._devices[remnawave_uuid] = [d for d in self._devices.get(remnawave_uuid, []) if d.hwid != hwid]

    async def list_internal_squads(self) -> list[dict]:
        return [
            {'uuid': 'mock-squad-de', 'name': 'Germany', 'country': 'DE'},
            {'uuid': 'mock-squad-nl', 'name': 'Netherlands', 'country': 'NL'},
        ]

    async def get_subscription_page_config(self, uuid: str) -> SubscriptionPageConfig | None:
        return SubscriptionPageConfig(
            uuid=uuid,
            platforms={
                'android': [
                    SubscriptionPageApp(id='happ', name='Happ', url_scheme='happ://add/', needs_base64=False),
                ],
                'ios': [
                    SubscriptionPageApp(id='happ', name='Happ', url_scheme='happ://add/', needs_base64=False),
                ],
            },
        )

    def _require_user(self, remnawave_uuid: str) -> RemnawaveUser:
        user = self._users.get(remnawave_uuid)
        if user is None:
            raise LookupError(f'MockRemnawaveClient: пользователь {remnawave_uuid} не найден')
        return user
