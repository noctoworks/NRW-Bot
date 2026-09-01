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
class SubscriptionPageButton:
    """Одна кнопка внутри блока инструкции — либо внешняя ссылка (магазин
    приложений/GitHub-релиз), либо deep-link на добавление подписки в
    приложение. `link` может содержать плейсхолдеры {{SUBSCRIPTION_LINK}}/
    {{USERNAME}} (см. Subpage Builder Remnawave) — подстановка на стороне
    caller'а (app/cabinet/routes.py), не здесь."""

    type: str  # 'external' | 'subscriptionLink'
    link: str
    text: dict[str, str] = field(default_factory=dict)  # locale -> подпись кнопки


@dataclass
class SubscriptionPageBlock:
    """Один шаг инструкции (см. референс sub_page — "Установка приложения",
    "Предупреждение", "Добавление подписки", "Если подписка не добавилась",
    "Подключение и использование") — рендерится как шаг вертикального
    таймлайна, поэтому title/description нужны ВСЕГДА, даже если у блока
    нет кнопок (чисто текстовые шаги вроде "Предупреждение" тоже часть
    таймлайна, не просто мусор для фильтрации)."""

    title: dict[str, str] = field(default_factory=dict)
    description: dict[str, str] = field(default_factory=dict)
    icon_key: str = ''
    icon_color: str = ''
    buttons: list[SubscriptionPageButton] = field(default_factory=list)


@dataclass
class SubscriptionPageApp:
    name: str
    featured: bool = False
    blocks: list[SubscriptionPageBlock] = field(default_factory=list)


@dataclass
class SubscriptionPagePlatform:
    key: str  # android|ios|windows|macos|linux|appleTV|androidTV
    display_name: dict[str, str] = field(default_factory=dict)  # locale -> название платформы
    apps: list[SubscriptionPageApp] = field(default_factory=list)


@dataclass
class SubscriptionPageConfig:
    platforms: list[SubscriptionPagePlatform] = field(default_factory=list)


class RemnawaveClient(ABC):
    @abstractmethod
    async def create_user(
        self,
        *,
        telegram_id: int,
        squad_uuids: list[str],
        traffic_limit_gb: int,
        expire_at: datetime,
        description: str | None = None,
    ) -> RemnawaveUser: ...

    @abstractmethod
    async def extend_user_expiration(
        self,
        *,
        remnawave_uuid: str,
        expire_at: datetime,
        traffic_limit_gb: int | None = None,
        squad_uuids: list[str] | None = None,
    ) -> RemnawaveUser:
        """traffic_limit_gb/squad_uuids — опциональные, только если продление идёт
        со сменой тарифа (см. subscription_provisioning.py/handlers/subscription.py):
        без них PATCH меняет только expireAt, старые лимиты/сквад на панели остаются
        от прежнего тарифа."""
        ...

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
    async def get_user_traffic_by_node(self, *, remnawave_uuid: str, days: int = 30) -> list[dict]:
        """Трафик пользователя по нодам за последние `days` дней:
        [{"node_uuid", "node_name", "country_code", "total_bytes"}, ...],
        отсортировано панелью по убыванию total. Для карточки пользователя в
        веб-админке (диалог 2026-09-01) — "трафик по нодам", не было в §5
        clone-architecture.md (сознательное расширение). Проверено вживую на
        тестовой панели: GET /bandwidth-stats/users/{id}?start=...&end=...
        &topNodesLimit=20 — id тот же numeric id, что и remnawave_uuid (см.
        комментарий в real.py про переход панели на numeric id)."""

    @abstractmethod
    async def remove_device(self, *, remnawave_uuid: str, hwid: str) -> None: ...

    @abstractmethod
    async def list_internal_squads(self) -> list[dict]:
        """[{"uuid": ..., "name": ..., "country": ...}, ...] — для сид-скрипта тарифа/ServerSquad."""

    @abstractmethod
    async def list_nodes(self) -> list[dict]:
        """[{"uuid", "name", "country_code", "is_connected", "is_disabled",
        "traffic_used_gb"}, ...] — для раздела "Ноды" веб-админки (см. диалог
        2026-09-01). Не было в исходном §5 clone-architecture.md (сознательное
        расширение по прямому запросу пользователя, не "на всякий случай"), см.
        app/cabinet/admin_routes.py::nodes. Панель реально отдаёт больше полей
        (CPU/память и т.п. под "Мониторинг" не проверялись — на GET /nodes их нет,
        нужен отдельный эндпоинт, если он вообще есть)."""

    @abstractmethod
    async def get_system_stats(self) -> dict:
        """Живые метрики ПАНЕЛИ (не отдельных нод — см. get_nodes_metrics ниже):
        {"cpu_cores", "memory_used_bytes", "memory_total_bytes", "uptime_seconds",
        "users_online_now", "users_online_last_day", "users_online_last_week",
        "users_never_online", "nodes_online", "nodes_total_bytes_lifetime"}.
        Проверено вживую на тестовой панели (диалог 2026-09-01): GET /system/stats.
        ВАЖНО: cpu/memory — это ресурсы машины, на которой крутится сама панель
        Remnawave, а НЕ аппаратные метрики VPN-нод — такого эндпоинта у панели нет."""

    @abstractmethod
    async def get_nodes_metrics(self) -> list[dict]:
        """Живой трафик и кол-во юзеров онлайн по каждой ноде с момента её
        последнего рестарта (не за произвольный период, панель не хранит историю):
        [{"node_uuid", "node_name", "users_online",
        "inbound_stats": [{"tag", "upload", "download"}, ...],
        "outbound_stats": [{"tag", "upload", "download"}, ...]}, ...].
        upload/download — уже отформатированные панелью строки ("926.70 MiB"),
        не байты — Remnawave не отдаёт сырое число здесь. Проверено вживую на
        тестовой панели (диалог 2026-09-01): GET /system/nodes/metrics."""

    @abstractmethod
    async def get_subscription_page_config(self) -> SubscriptionPageConfig | None:
        """One-tap connect (§8) — конфиг Subpage Builder панели: список VPN-клиентов
        по платформам с реальными deep-link-схемами (не наши догадки в Mini App).
        Глобальный для всей панели, НЕ привязан к конкретному пользователю/shortUuid —
        поэтому без параметров."""
