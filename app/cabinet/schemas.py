"""Pydantic-модели ответов/запросов /cabinet/*. Только поля, нужные Dashboard +
Payment экранам Mini App (см. план) — не полный слепок ORM-моделей."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuthRequest(BaseModel):
    init_data: str


class AuthResponse(BaseModel):
    access_token: str


class SubscriptionOut(BaseModel):
    status: str
    end_date: datetime
    traffic_limit_gb: int
    traffic_used_gb: float
    device_limit: int
    subscription_url: str | None


class DashboardResponse(BaseModel):
    balance_kopeks: int
    subscription: SubscriptionOut | None
    is_admin: bool


class PeriodOut(BaseModel):
    days: int
    label: str
    price_kopeks: int


class PaymentMethodOut(BaseModel):
    id: str
    label: str


class TariffResponse(BaseModel):
    name: str
    periods: list[PeriodOut]
    payment_methods: list[PaymentMethodOut]


class PurchaseRequest(BaseModel):
    period_days: int
    method: str


class PurchaseResponse(BaseModel):
    status: str  # success|pending
    payment_url: str | None = None
    subscription: SubscriptionOut | None = None


class ConnectButtonOut(BaseModel):
    type: str  # external|subscriptionLink — определяет стиль кнопки на фронте
    label: str
    url: str


class ConnectBlockOut(BaseModel):
    """Один шаг инструкции ("Установка приложения", "Предупреждение", ...) —
    рендерится как шаг вертикального таймлайна, см. app/external/remnawave/base.py."""

    title: str
    description: str
    icon_key: str
    icon_color: str
    buttons: list[ConnectButtonOut]


class ConnectAppOut(BaseModel):
    id: str
    name: str
    featured: bool
    blocks: list[ConnectBlockOut]


class ConnectPlatformOut(BaseModel):
    key: str
    label: str
    apps: list[ConnectAppOut]


class ConnectAppsResponse(BaseModel):
    platforms: list[ConnectPlatformOut]


class ReferralResponse(BaseModel):
    referral_link: str
    percent: int
    invited_count: int
    earned_kopeks: int
    # Ближайший непройденный порог REFERRAL_MILESTONES (см.
    # services/referral_service.py) — null, если все известные пороги уже
    # пройдены. Даёт фронту показать прогресс-бар "ещё N друзей до бонуса".
    next_milestone_at: int | None = None
    next_milestone_bonus_days: int | None = None


class ProfileResponse(BaseModel):
    telegram_id: int
    username: str | None
    full_name: str | None
    language: str
    balance_kopeks: int
    created_at: datetime


class TransactionOut(BaseModel):
    id: int
    type: str
    amount_kopeks: int
    status: str
    description: str | None
    created_at: datetime


class PaginatedTransactionsResponse(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    total_pages: int


class DeviceOut(BaseModel):
    hwid: str
    platform: str
    device_model: str
    created_at: datetime | None


class PromoCodeRequest(BaseModel):
    code: str


class PromoCodeResponse(BaseModel):
    type: str  # balance|days
    value: int


class GiftPurchaseRequest(BaseModel):
    period_days: int
    method: str


class GiftPurchaseResponse(BaseModel):
    status: str  # success|pending
    gift_link: str | None = None
    payment_url: str | None = None


class LanguageRequest(BaseModel):
    language: str  # ru|en


class LanguageResponse(BaseModel):
    language: str
