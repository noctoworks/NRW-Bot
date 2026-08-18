"""Pydantic-модели ответов /cabinet/admin/*. Числа денег — везде kopeks (int),
форматирование в рубли — на фронте (как и в остальном /cabinet/*)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OverviewResponse(BaseModel):
    revenue_today_kopeks: int
    revenue_7d_kopeks: int
    revenue_30d_kopeks: int
    active_subscriptions: int
    total_users: int
    new_users_7d: int
    conversion_percent: float
    avg_check_kopeks: int
    mrr_kopeks: int
    arr_kopeks: int
    churn_percent_30d: float


class RevenuePointOut(BaseModel):
    date: str
    revenue_kopeks: int
    count: int


class TopPayerOut(BaseModel):
    user_id: int
    telegram_id: int
    username: str | None
    total_kopeks: int


class LtvResponse(BaseModel):
    arpu_kopeks: int
    avg_ltv_paying_kopeks: int
    median_ltv_kopeks: int
    paying_users_count: int
    top_payers: list[TopPayerOut]


class CohortOut(BaseModel):
    cohort_month: str
    users_count: int
    revenue_per_user_by_month_offset: list[int]


class CohortsResponse(BaseModel):
    max_months: int
    cohorts: list[CohortOut]


class TopReferrerOut(BaseModel):
    user_id: int
    telegram_id: int
    username: str | None
    earnings_kopeks: int
    referred_count: int


class ReferralFunnelResponse(BaseModel):
    referred_users_count: int
    referred_paying_count: int
    conversion_percent: float
    total_earnings_kopeks: int
    top_referrers: list[TopReferrerOut]


class AdminUserListItem(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    is_blocked: bool
    has_active_subscription: bool
    last_activity_at: datetime | None
    created_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserListItem]
    total: int
    page: int
    total_pages: int


class AdminSubscriptionOut(BaseModel):
    status: str
    end_date: datetime
    traffic_limit_gb: int
    traffic_used_gb: float
    device_limit: int


class AdminTransactionOut(BaseModel):
    id: int
    type: str
    amount_kopeks: int
    status: str
    description: str | None
    created_at: datetime


class AdminUserDetailResponse(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    language: str
    is_blocked: bool
    blocked_bot: bool
    balance_kopeks: int
    created_at: datetime
    last_activity_at: datetime | None
    subscription: AdminSubscriptionOut | None
    transactions: list[AdminTransactionOut]
    referrals_invited_count: int
    referrals_earned_kopeks: int


class BalanceAdjustRequest(BaseModel):
    amount_rub: float


class BlockRequest(BaseModel):
    blocked: bool


class MessageRequest(BaseModel):
    text: str


class MassbanRequest(BaseModel):
    telegram_ids: list[int]


class MassbanResponse(BaseModel):
    blocked_count: int
    requested_count: int
