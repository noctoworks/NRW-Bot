"""Интерфейс, который повторяют MockRemnawaveClient и (позже) RealRemnawaveClient.

Подмножество методов взято из §5 clone-architecture.md — сверено построчно
с реальным app/external/remnawave_api.py у Bedolaga. Не добавлять сюда методы
"на всякий случай" — если он не упомянут в §5 документа, значит он не нужен ресейлеру.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RemnawaveUser:
    uuid: str
    subscription_url: str
    short_uuid: str
    traffic_used_gb: float = 0.0
    traffic_limit_gb: int = 0
    expire_at: datetime | None = None
    is_enabled: bool = True


@dataclass
class RemnawaveDevice:
    hwid: str
    platform: str = ''
    device_model: str = ''
    created_at: datetime | None = None


@dataclass
class SubscriptionPageApp:
    id: str
    name: str
    url_scheme: str
    needs_base64: bool = False


@dataclass
class SubscriptionPageConfig:
    uuid: str
    # platform_key -> список приложений, см. §8 clone-architecture.md
    platforms: dict[str, list[SubscriptionPageApp]] = field(default_factory=dict)


class RemnawaveClient(ABC):
    @abstractmethod
    async def create_user(
        self, *, telegram_id: int, squad_uuids: list[str], traffic_limit_gb: int, expire_at: datetime
    ) -> RemnawaveUser: ...

    @abstractmethod
    async def extend_user_expiration(self, *, remnawave_uuid: str, expire_at: datetime) -> RemnawaveUser: ...

    @abstractmethod
    async def enable_user(self, *, remnawave_uuid: str) -> None: ...

    @abstractmethod
    async def disable_user(self, *, remnawave_uuid: str) -> None: ...

    @abstractmethod
    async def revoke_user_subscription(self, *, remnawave_uuid: str) -> RemnawaveUser:
        """Перевыпуск ссылки подписки (новый short_uuid/subscription_url)."""

    @abstractmethod
    async def reset_user_traffic(self, *, remnawave_uuid: str) -> None: ...

    @abstractmethod
    async def get_subscription_info(self, *, remnawave_uuid: str) -> RemnawaveUser: ...

    @abstractmethod
    async def get_user_devices(self, *, remnawave_uuid: str) -> list[RemnawaveDevice]: ...

    @abstractmethod
    async def reset_user_devices(self, *, remnawave_uuid: str) -> None: ...

    @abstractmethod
    async def remove_device(self, *, remnawave_uuid: str, hwid: str) -> None: ...

    @abstractmethod
    async def list_internal_squads(self) -> list[dict]:
        """[{"uuid": ..., "name": ..., "country": ...}, ...] — для сид-скрипта тарифа/ServerSquad."""

    @abstractmethod
    async def get_subscription_page_config(self, uuid: str) -> SubscriptionPageConfig | None:
        """One-tap connect (§8) — список VPN-клиентов и их deep-link-схем."""
