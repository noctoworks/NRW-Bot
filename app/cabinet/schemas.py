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
