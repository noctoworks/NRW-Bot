"""Аналитика для веб-админки (/cabinet/admin/*, см. app/cabinet/admin_routes.py).

Определение "выручки": Transaction.type IN ('subscription_payment', 'gift')
AND status='completed' — это единственные два типа транзакций, которые
означают "юзер реально заплатил деньги" (subscription_payment — покупка/
продление своей подписки, gift — покупка подарочного кода кому-то). НЕ
'topup': в этом продукте нет пользовательского пополнения баланса без
покупки — 'topup' создаётся ТОЛЬКО при ручном начислении админом
(app/cabinet/admin_routes.py::adjust_balance, handlers/admin.py::
on_admin_balance_input) или бонусе кампании (services/campaign_service.py) —
то есть деньги, которые бизнес сам раздал, а не заработал. Раньше здесь было
('subscription_payment', 'topup') — унаследовано от того же бага в
app/handlers/admin.py::_render_subs_stats (исправлено там же одновременно с
этим файлом, см. диалог) — обе цифры считались завышенными на сумму всех
админских/кампанейских начислений.

Методологическая оговорка (см. диалог, важно для пользователя как для
бизнес-человека): у сервиса нет реального recurring billing — MRR/ARR тут
НЕ "сумма активных подписок с автосписанием" (такого нет в модели), а прокси
"выручка за последние 30 дней" (и ×12 для ARR). В UI это должно быть
подписано явно, не выдаваться за точную SaaS-метрику.

Группировки по датам считаются в Python над выгруженными строками, а не через
SQL date_trunc/strftime — чтобы одинаково работать на SQLite (dev) и Postgres
(прод) без дублирования диалект-специфичных запросов.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Payment, ReferralEarning, Subscription, Tariff, Transaction, User
from app.services.time_utils import business_day_start_utc

REVENUE_TYPES = ('subscription_payment', 'gift')

# Оплата собственным балансом (handlers/subscription.py, method='balance') не
# заводит в систему новых денег — это уже начисленные ранее рефералки/бонусы/
# промокоды, которые пользователь просто тратит (см. referral_service.py::
# credit_referral_earning — та же логика уже применена там же). Без этого
# исключения выручка/MRR/ARR/LTV/когорты завышаются на сумму любых покупок,
# оплаченных бонусным балансом — тот же класс бага, что раньше был с 'topup'
# (см. докстринг модуля), просто вылезший через новый способ оплаты.
_NOT_BALANCE_FUNDED = ~(
    select(Payment.id).where(Payment.transaction_id == Transaction.id, Payment.provider == 'balance').exists()
)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _revenue_sum(db: AsyncSession, *, since: datetime | None = None) -> int:
    stmt = select(func.coalesce(func.sum(Transaction.amount_kopeks), 0)).where(
        Transaction.type.in_(REVENUE_TYPES), Transaction.status == 'completed', _NOT_BALANCE_FUNDED
    )
    if since is not None:
        stmt = stmt.where(Transaction.created_at >= since)
    return (await db.execute(stmt)).scalar_one()


async def get_overview(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    today_start = business_day_start_utc(now)

    revenue_today = await _revenue_sum(db, since=today_start)
    revenue_7d = await _revenue_sum(db, since=now - timedelta(days=7))
    revenue_30d = await _revenue_sum(db, since=now - timedelta(days=30))
    revenue_all_time = await _revenue_sum(db)

    active_subscriptions = (
        await db.execute(select(func.count(Subscription.id)).where(Subscription.status == 'active'))
    ).scalar_one()

    # "Платящих" — активные И не триальные (Subscription.is_trial=False), в
    # отличие от active_subscriptions выше, который триал не отделяет.
    # "+сегодня" — только ЖИВЫЕ новые (never had-a-row-before) платные подписки:
    # created_at сегодня. НЕ ловит конверсию триал→платная тем же днём — при
    # продлении/переводе на платную существующая Subscription-строка правится
    # in-place (см. subscription_provisioning.py::provision_or_extend_subscription),
    # created_at остаётся от первой выдачи (в т.ч. от триала). Так и задумано —
    # это счётчик новых подписчиков, а не платежей (см. диалог).
    paying_subscriptions = (
        await db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status == 'active', Subscription.is_trial.is_(False)
            )
        )
    ).scalar_one()
    new_paying_subscriptions_today = (
        await db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.is_trial.is_(False), Subscription.created_at >= today_start
            )
        )
    ).scalar_one()

    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    new_users_7d = (
        await db.execute(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=7)))
    ).scalar_one()

    paying_users = (
        await db.execute(
            select(func.count(func.distinct(Transaction.user_id))).where(
                Transaction.type.in_(REVENUE_TYPES), Transaction.status == 'completed', _NOT_BALANCE_FUNDED
            )
        )
    ).scalar_one()
    conversion_percent = round(paying_users / total_users * 100, 1) if total_users else 0.0

    tx_count_30d = (
        await db.execute(
            select(func.count(Transaction.id)).where(
                Transaction.type.in_(REVENUE_TYPES),
                Transaction.status == 'completed',
                Transaction.created_at >= now - timedelta(days=30),
                _NOT_BALANCE_FUNDED,
            )
        )
    ).scalar_one()
    avg_check_kopeks = round(revenue_30d / tx_count_30d) if tx_count_30d else 0

    churn_percent_30d = await _churn_percent(db, since=now - timedelta(days=30), until=now)

    # traffic_used_gb синхронизируется фоновой задачей из Remnawave в саму
    # Subscription (см. models.py) — не живой запрос к панели, поэтому сумма
    # по активным подпискам дешёвая (см. диалог 2026-09-01, дашборд "Обзор").
    total_traffic_gb = (
        await db.execute(
            select(func.coalesce(func.sum(Subscription.traffic_used_gb), 0)).where(Subscription.status == 'active')
        )
    ).scalar_one()

    return {
        'revenue_today_kopeks': revenue_today,
        'revenue_7d_kopeks': revenue_7d,
        'revenue_30d_kopeks': revenue_30d,
        'revenue_all_time_kopeks': revenue_all_time,
        'active_subscriptions': active_subscriptions,
        'paying_subscriptions': paying_subscriptions,
        'new_paying_subscriptions_today': new_paying_subscriptions_today,
        'total_users': total_users,
        'new_users_7d': new_users_7d,
        'conversion_percent': conversion_percent,
        'avg_check_kopeks': avg_check_kopeks,
        'mrr_kopeks': revenue_30d,
        'arr_kopeks': revenue_30d * 12,
        'churn_percent_30d': churn_percent_30d,
        'total_traffic_gb': round(total_traffic_gb, 1),
    }


async def _churn_percent(db: AsyncSession, *, since: datetime, until: datetime) -> float:
    """Доля подписок, у которых end_date попал в [since, until] и которые
    СЕЙЧАС status='expired' (не продлили) — среди всех, у кого end_date вообще
    попал в этот диапазон."""
    result = await db.execute(
        select(Subscription.status).where(Subscription.end_date >= since, Subscription.end_date <= until)
    )
    statuses = [row[0] for row in result.all()]
    if not statuses:
        return 0.0
    churned = sum(1 for s in statuses if s == 'expired')
    return round(churned / len(statuses) * 100, 1)


async def get_revenue_timeseries(db: AsyncSession, *, days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Transaction.created_at, Transaction.amount_kopeks).where(
            Transaction.type.in_(REVENUE_TYPES),
            Transaction.status == 'completed',
            Transaction.created_at >= since,
            _NOT_BALANCE_FUNDED,
        )
    )
    buckets: dict[date, dict] = defaultdict(lambda: {'revenue_kopeks': 0, 'count': 0})
    for created_at, amount_kopeks in result.all():
        day = _as_utc(created_at).date()
        buckets[day]['revenue_kopeks'] += amount_kopeks
        buckets[day]['count'] += 1

    today = datetime.now(timezone.utc).date()
    series = []
    for offset in range(days, -1, -1):
        day = today - timedelta(days=offset)
        bucket = buckets.get(day, {'revenue_kopeks': 0, 'count': 0})
        series.append({'date': day.isoformat(), 'revenue_kopeks': bucket['revenue_kopeks'], 'count': bucket['count']})
    return series


async def get_ltv(db: AsyncSession) -> dict:
    result = await db.execute(
        select(Transaction.user_id, func.sum(Transaction.amount_kopeks))
        .where(Transaction.type.in_(REVENUE_TYPES), Transaction.status == 'completed', _NOT_BALANCE_FUNDED)
        .group_by(Transaction.user_id)
    )
    per_user: dict[int, int] = {user_id: total for user_id, total in result.all()}

    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    totals = list(per_user.values())

    arpu_kopeks = round(sum(totals) / total_users) if total_users else 0
    avg_ltv_paying_kopeks = round(statistics.fmean(totals)) if totals else 0
    median_ltv_kopeks = round(statistics.median(totals)) if totals else 0

    top_ids = sorted(per_user.items(), key=lambda kv: kv[1], reverse=True)[:20]
    top_payers = []
    if top_ids:
        users_result = await db.execute(select(User).where(User.id.in_([uid for uid, _ in top_ids])))
        users_by_id = {u.id: u for u in users_result.scalars().all()}
        for user_id, total_kopeks in top_ids:
            user = users_by_id.get(user_id)
            if user is None:
                continue
            top_payers.append(
                {
                    'user_id': user.id,
                    'telegram_id': user.telegram_id,
                    'username': user.username,
                    'full_name': user.full_name,
                    'total_kopeks': total_kopeks,
                }
            )

    return {
        'arpu_kopeks': arpu_kopeks,
        'avg_ltv_paying_kopeks': avg_ltv_paying_kopeks,
        'median_ltv_kopeks': median_ltv_kopeks,
        'paying_users_count': len(totals),
        'top_payers': top_payers,
    }


def _month_key(dt: datetime) -> tuple[int, int]:
    dt = _as_utc(dt)
    return dt.year, dt.month


def _month_offset(from_key: tuple[int, int], to_key: tuple[int, int]) -> int:
    return (to_key[0] - from_key[0]) * 12 + (to_key[1] - from_key[1])


async def get_cohorts(db: AsyncSession, *, max_months: int = 6) -> dict:
    users_result = await db.execute(select(User.id, User.created_at))
    cohort_by_user: dict[int, tuple[int, int]] = {user_id: _month_key(created_at) for user_id, created_at in users_result.all()}

    cohort_sizes: dict[tuple[int, int], int] = defaultdict(int)
    for cohort in cohort_by_user.values():
        cohort_sizes[cohort] += 1

    tx_result = await db.execute(
        select(Transaction.user_id, Transaction.created_at, Transaction.amount_kopeks).where(
            Transaction.type.in_(REVENUE_TYPES), Transaction.status == 'completed', _NOT_BALANCE_FUNDED
        )
    )
    revenue_by_cohort_offset: dict[tuple[int, int], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for user_id, created_at, amount_kopeks in tx_result.all():
        cohort = cohort_by_user.get(user_id)
        if cohort is None:
            continue
        offset = _month_offset(cohort, _month_key(created_at))
        if 0 <= offset <= max_months:
            revenue_by_cohort_offset[cohort][offset] += amount_kopeks

    cohorts = []
    for cohort in sorted(cohort_sizes.keys()):
        size = cohort_sizes[cohort]
        by_offset = revenue_by_cohort_offset.get(cohort, {})
        revenue_per_user_by_offset = [round(by_offset.get(offset, 0) / size) for offset in range(max_months + 1)]
        cohorts.append(
            {
                'cohort_month': f'{cohort[0]:04d}-{cohort[1]:02d}',
                'users_count': size,
                'revenue_per_user_by_month_offset': revenue_per_user_by_offset,
            }
        )

    return {'max_months': max_months, 'cohorts': cohorts}


async def get_referral_funnel(db: AsyncSession) -> dict:
    referred_users_count = (
        await db.execute(select(func.count(User.id)).where(User.referred_by_id.is_not(None)))
    ).scalar_one()

    referred_paying_result = await db.execute(
        select(func.count(func.distinct(Transaction.user_id)))
        .select_from(Transaction)
        .join(User, User.id == Transaction.user_id)
        .where(
            User.referred_by_id.is_not(None),
            Transaction.type.in_(REVENUE_TYPES),
            Transaction.status == 'completed',
            _NOT_BALANCE_FUNDED,
        )
    )
    referred_paying_count = referred_paying_result.scalar_one()
    conversion_percent = round(referred_paying_count / referred_users_count * 100, 1) if referred_users_count else 0.0

    total_earnings_kopeks = (
        await db.execute(select(func.coalesce(func.sum(ReferralEarning.amount_kopeks), 0)))
    ).scalar_one()

    top_result = await db.execute(
        select(ReferralEarning.user_id, func.sum(ReferralEarning.amount_kopeks), func.count(func.distinct(ReferralEarning.source_user_id)))
        .group_by(ReferralEarning.user_id)
        .order_by(func.sum(ReferralEarning.amount_kopeks).desc())
        .limit(20)
    )
    top_rows = top_result.all()
    top_referrers = []
    if top_rows:
        users_result = await db.execute(select(User).where(User.id.in_([row[0] for row in top_rows])))
        users_by_id = {u.id: u for u in users_result.scalars().all()}
        for user_id, earnings_kopeks, referred_count in top_rows:
            user = users_by_id.get(user_id)
            if user is None:
                continue
            top_referrers.append(
                {
                    'user_id': user.id,
                    'telegram_id': user.telegram_id,
                    'username': user.username,
                    'full_name': user.full_name,
                    'earnings_kopeks': earnings_kopeks,
                    'referred_count': referred_count,
                }
            )

    return {
        'referred_users_count': referred_users_count,
        'referred_paying_count': referred_paying_count,
        'conversion_percent': conversion_percent,
        'total_earnings_kopeks': total_earnings_kopeks,
        'top_referrers': top_referrers,
    }


async def get_recent_payments(db: AsyncSession, *, limit: int = 10) -> list[dict]:
    """Лента последних платежей для главного экрана новой админки (см. диалог
    2026-09-01, "максимально прозрачная аналитика") — та же выручка, что и
    _revenue_sum выше (REVENUE_TYPES, status='completed', НЕ оплата балансом),
    просто последние N штук вместо суммы."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.type.in_(REVENUE_TYPES), Transaction.status == 'completed', _NOT_BALANCE_FUNDED)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
    )
    transactions = list(result.scalars())
    if not transactions:
        return []

    users_result = await db.execute(select(User).where(User.id.in_([t.user_id for t in transactions])))
    users_by_id = {u.id: u for u in users_result.scalars().all()}

    payments = []
    for t in transactions:
        user = users_by_id.get(t.user_id)
        if user is None:
            continue
        payments.append(
            {
                'user_id': user.id,
                'telegram_id': user.telegram_id,
                'username': user.username,
                'full_name': user.full_name,
                'amount_kopeks': t.amount_kopeks,
                'type': t.type,
                'created_at': t.created_at,
            }
        )
    return payments


async def get_revenue_by_type(db: AsyncSession, *, days: int = 30) -> list[dict]:
    """Разбивка выручки по REVENUE_TYPES (см. докстринг модуля) — ТОЛЬКО
    subscription_payment/gift, не все типы Transaction: 'topup' и
    'referral_reward' — это деньги, которые бизнес сам раздал, а не заработал
    (см. докстринг), включать их в "доход по типу" было бы тем же завышением,
    что уже один раз ловили в этом файле. Отсюда всего 2 категории, а не 5 —
    так и должно быть, не баг диаграммы."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Transaction.type, func.coalesce(func.sum(Transaction.amount_kopeks), 0))
        .where(
            Transaction.type.in_(REVENUE_TYPES),
            Transaction.status == 'completed',
            Transaction.created_at >= since,
            _NOT_BALANCE_FUNDED,
        )
        .group_by(Transaction.type)
    )
    by_type = dict(result.all())
    return [{'type': t, 'revenue_kopeks': by_type.get(t, 0)} for t in REVENUE_TYPES]


async def get_revenue_by_provider(db: AsyncSession, *, days: int = 30) -> list[dict]:
    """Разбивка выручки по Payment.provider — 'balance' (оплата бонусным
    балансом) намеренно исключён, той же логикой, что и _NOT_BALANCE_FUNDED
    в остальном файле: это не новые деньги, а трата уже начисленных ранее
    бонусов/рефералки."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Payment.provider, func.coalesce(func.sum(Transaction.amount_kopeks), 0))
        .join(Transaction, Transaction.id == Payment.transaction_id)
        .where(
            Transaction.type.in_(REVENUE_TYPES),
            Transaction.status == 'completed',
            Transaction.created_at >= since,
            Payment.provider != 'balance',
        )
        .group_by(Payment.provider)
        .order_by(func.sum(Transaction.amount_kopeks).desc())
    )
    return [{'provider': provider, 'revenue_kopeks': revenue} for provider, revenue in result.all()]


async def get_revenue_by_weekday(db: AsyncSession, *, days: int = 90) -> list[dict]:
    """Доход по дням недели — в Python над выгруженными строками (см.
    докстринг модуля про date_trunc/strftime), 90 дней по умолчанию (не 30,
    как у остальных разрезов) — дню недели нужно больше данных, чтобы не
    быть шумом одной случайной недели."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Transaction.created_at, Transaction.amount_kopeks).where(
            Transaction.type.in_(REVENUE_TYPES),
            Transaction.status == 'completed',
            Transaction.created_at >= since,
            _NOT_BALANCE_FUNDED,
        )
    )
    buckets = [0] * 7  # datetime.weekday(): 0=понедельник .. 6=воскресенье
    for created_at, amount_kopeks in result.all():
        buckets[_as_utc(created_at).weekday()] += amount_kopeks
    return [{'weekday': i, 'revenue_kopeks': buckets[i]} for i in range(7)]


async def get_active_subscriptions_by_tariff(db: AsyncSession) -> list[dict]:
    """Прокси-метрика вместо "выручки по тарифам" (см. диалог 2026-09-01):
    Transaction не хранит tariff_id, только текущий Subscription.tariff_id —
    для старых покупок это было бы неверно, если юзер сменил тариф. Поэтому
    здесь — снимок СЕЙЧАС: сколько активных подписок на каждом тарифе, не
    сколько денег этот тариф принёс исторически."""
    result = await db.execute(
        select(Tariff.name, func.count(Subscription.id))
        .join(Subscription, Subscription.tariff_id == Tariff.id)
        .where(Subscription.status == 'active')
        .group_by(Tariff.name)
        .order_by(func.count(Subscription.id).desc())
    )
    return [{'tariff_name': name, 'active_count': count} for name, count in result.all()]
