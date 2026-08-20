"""Pydantic-модели ответов /cabinet/admin/*. Числа денег — везде kopeks (int),
форматирование в рубли — на фронте (как и в остальном /cabinet/*)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OverviewResponse(BaseModel):
    revenue_today_kopeks: int
    revenue_7d_kopeks: int
    revenue_30d_kopeks: int
    revenue_all_time_kopeks: int
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
    full_name: str | None
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
    full_name: str | None
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
    full_name: str | None
    is_blocked: bool
    has_active_subscription: bool
    is_trial: bool
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
    is_trial: bool


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
    full_name: str | None
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
    referral_commission_percent: int | None
    promo_group_id: int | None
    promo_group_name: str | None


class BalanceAdjustRequest(BaseModel):
    amount_rub: float


class SubscriptionDaysAdjustRequest(BaseModel):
    days: int


class BlockRequest(BaseModel):
    blocked: bool


class MessageRequest(BaseModel):
    text: str


class MassbanRequest(BaseModel):
    telegram_ids: list[int]


class MassbanResponse(BaseModel):
    blocked_count: int
    requested_count: int


class ReferralCommissionRequest(BaseModel):
    commission_percent: int | None = Field(default=None, ge=0, le=100)


class DeviceOut(BaseModel):
    hwid: str
    platform: str
    device_model: str
    created_at: datetime | None


class SyncResultResponse(BaseModel):
    status: str
    subscription: AdminSubscriptionOut | None = None


class PaginatedTransactionsResponse(BaseModel):
    items: list[AdminTransactionOut]
    total: int
    page: int
    total_pages: int


class PromoGroupOut(BaseModel):
    id: int
    name: str
    discount_percent: int
    users_count: int


class PromoGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    discount_percent: int = Field(ge=0, le=100)


class PromoGroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    discount_percent: int | None = Field(default=None, ge=0, le=100)


class SetUserPromoGroupRequest(BaseModel):
    promo_group_id: int | None = None


class CampaignOut(BaseModel):
    id: int
    name: str
    start_parameter: str
    bonus_type: str
    balance_bonus_kopeks: int
    subscription_duration_days: int | None
    is_active: bool
    deep_link: str


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    start_parameter: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    bonus_type: str = Field(pattern=r'^(balance|subscription|none)$')
    balance_bonus_kopeks: int = Field(default=0, ge=0)
    subscription_duration_days: int | None = Field(default=None, ge=1)


class CampaignUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    balance_bonus_kopeks: int | None = Field(default=None, ge=0)
    subscription_duration_days: int | None = Field(default=None, ge=1)


class CampaignStatsResponse(BaseModel):
    registrations_count: int
    paying_count: int
    conversion_percent: float
    revenue_kopeks: int
