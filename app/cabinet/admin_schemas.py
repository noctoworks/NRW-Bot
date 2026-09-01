"""Pydantic-модели ответов /cabinet/admin/*. Числа денег — везде kopeks (int),
форматирование в рубли — на фронте (как и в остальном /cabinet/*)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OverviewResponse(BaseModel):
    revenue_today_kopeks: int
    revenue_7d_kopeks: int
    revenue_30d_kopeks: int
    revenue_all_time_kopeks: int
    active_subscriptions: int
    paying_subscriptions: int
    new_paying_subscriptions_today: int
    total_users: int
    new_users_7d: int
    conversion_percent: float
    avg_check_kopeks: int
    mrr_kopeks: int
    arr_kopeks: int
    churn_percent_30d: float
    total_traffic_gb: float


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


class NodeOut(BaseModel):
    uuid: str
    name: str
    country_code: str
    is_connected: bool
    is_disabled: bool
    traffic_used_gb: float


class RecentPaymentOut(BaseModel):
    user_id: int
    telegram_id: int
    username: str | None
    full_name: str | None
    amount_kopeks: int
    type: str
    created_at: datetime


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


class AdminTransactionListItem(AdminTransactionOut):
    """То же, что AdminTransactionOut, плюс кто платил — единый список
    /transactions (см. диалог 2026-09-01, "решить вопрос по транзакциям")
    показывает транзакции ПО ВСЕМ пользователям, не внутри одной карточки,
    поэтому нужна личность плательщика в каждой строке."""

    user_id: int
    telegram_id: int
    username: str | None
    full_name: str | None
    # provider/external_id — НЕ у каждой Transaction есть Payment (топап
    # админом/реферальный бонус ничего не платят провайдеру) — оба None в
    # этом случае. Нужны фронту, чтобы сопоставить строку с записью Platega
    # при сверке (см. GET /transactions/platega-reconcile ниже).
    payment_provider: str | None
    payment_external_id: str | None


class TransactionListResponse(BaseModel):
    items: list[AdminTransactionListItem]
    total: int
    page: int
    total_pages: int


class AdminTransactionDetailResponse(AdminTransactionListItem):
    """«Тело транзакции» (см. диалог 2026-09-01, клик по строке в /transactions)
    — то же, что в списке, плюс всё, что знаем про сам платёж: статус на нашей
    стороне, служебный контекст провижининга (raw_payload) и последний сырой
    ответ провайдера (provider_raw_response, см. Payment в models.py) — то,
    ради чего изначально заводили это поле при сверке с Platega. Оба None,
    если у транзакции вообще нет Payment (топап админом/реферальный бонус)."""

    payment_status: str | None
    payment_raw_payload: dict | None
    provider_raw_response: dict | None


class AdminSubscriptionListItem(BaseModel):
    """Подписки по ВСЕМ пользователям (см. диалог 2026-09-01) — раньше видна
    была только внутри карточки одного юзера (AdminUserDetailResponse.
    subscription). Только наши данные (Subscription/Tariff), без обращений
    к Remnawave — traffic_used_gb уже синхронизирован фоновой задачей (см.
    analytics_service.get_overview::total_traffic_gb)."""

    user_id: int
    telegram_id: int
    username: str | None
    full_name: str | None
    tariff_name: str
    status: str
    is_trial: bool
    end_date: datetime
    traffic_used_gb: float
    traffic_limit_gb: int
    device_limit: int
    autopay_enabled: bool


class SubscriptionListResponse(BaseModel):
    items: list[AdminSubscriptionListItem]
    total: int
    page: int
    total_pages: int


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


class SupportThreadOut(BaseModel):
    ticket_id: int
    status: str
    assigned_admin_name: str | None
    user_id: int
    telegram_id: int
    username: str | None
    full_name: str | None
    last_message: str
    last_message_at: datetime
    unread: bool


class SupportMessageOut(BaseModel):
    id: int
    direction: str
    body: str
    created_at: datetime


class SupportThreadDetailResponse(BaseModel):
    ticket_id: int
    status: str
    assigned_admin_name: str | None
    user_id: int
    telegram_id: int
    username: str | None
    full_name: str | None
    messages: list[SupportMessageOut]


class SupportReplyRequest(BaseModel):
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


class UserNodeTrafficOut(BaseModel):
    node_uuid: str
    node_name: str
    country_code: str
    total_bytes: int


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


class PromoCodeOut(BaseModel):
    id: int
    code: str
    type: Literal['balance', 'days']
    value: int
    max_activations: int
    activations_count: int
    expires_at: datetime | None
    is_active: bool
    created_at: datetime


class PromoCodeCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    type: Literal['balance', 'days']
    # value — копейки для balance, дни для days (см. PromoCode.value в models.py
    # и app/services/promocode_service.py::activate_promocode). gt=0 — тот же
    # инвариант, что уже проверяет создание промокода в чат-админке
    # (handlers/admin.py) — 0/отрицательный номинал бессмысленен.
    value: int = Field(gt=0)
    max_activations: int = Field(gt=0, default=1)
    # Ни один существующий промокод не имеет expires_at — в чат-админке (см.
    # handlers/admin.py) поле только ОТОБРАЖАЕТСЯ ("бессрочно"), но никогда не
    # заполняется при создании. Тут добавляем реальную возможность его задать —
    # осознанное расширение возможностей чат-версии, не паритет 1:1.
    expires_at: datetime | None = None


class PromoCodeUpdateRequest(BaseModel):
    # Только переключение активности — ровно то, что умеет чат-админка
    # (cb_promo_toggle); значение/тип/лимит активаций после создания не
    # редактируются нигде, не изобретаем новую возможность здесь.
    is_active: bool


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


class PanelStatsOut(BaseModel):
    cpu_cores: int
    memory_used_bytes: int
    memory_total_bytes: int
    uptime_seconds: float
    users_online_now: int
    users_online_last_day: int
    users_online_last_week: int
    users_never_online: int
    nodes_online: int
    nodes_total_bytes_lifetime: int


class NodeMetricStat(BaseModel):
    tag: str
    upload: str
    download: str


class NodeMetricOut(BaseModel):
    node_uuid: str
    node_name: str
    users_online: int
    inbound_stats: list[NodeMetricStat]
    outbound_stats: list[NodeMetricStat]


class MonitoringResponse(BaseModel):
    panel: PanelStatsOut
    nodes: list[NodeMetricOut]


class RevenueByTypeOut(BaseModel):
    type: str
    revenue_kopeks: int


class RevenueByProviderOut(BaseModel):
    provider: str
    revenue_kopeks: int


class RevenueByWeekdayOut(BaseModel):
    weekday: int
    revenue_kopeks: int


class ActiveSubsByTariffOut(BaseModel):
    tariff_name: str
    active_count: int


class SalesBreakdownResponse(BaseModel):
    by_type: list[RevenueByTypeOut]
    by_provider: list[RevenueByProviderOut]
    by_weekday: list[RevenueByWeekdayOut]
    active_subs_by_tariff: list[ActiveSubsByTariffOut]
