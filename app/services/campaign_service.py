"""Маркетинговые кампании (см. Campaign/CampaignRegistration в models.py,
диалог Фаза 4). Бонус начисляется ровно один раз при регистрации нового
пользователя (handlers/start.py) — не на каждый повторный переход по ссылке.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Campaign, CampaignRegistration, Tariff, Transaction, User
from app.services.analytics_service import REVENUE_TYPES

logger = logging.getLogger(__name__)


async def get_campaign_by_start_parameter(db: AsyncSession, start_parameter: str) -> Campaign | None:
    result = await db.execute(
        select(Campaign).where(Campaign.start_parameter == start_parameter, Campaign.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def apply_campaign_bonus(db: AsyncSession, *, campaign: Campaign, user: User) -> None:
    """Начисляет бонус кампании новому пользователю и фиксирует
    CampaignRegistration (для статистики и дедупа). Не бросает исключение
    наружу — та же логика, что у credit_referral_earning: атрибуция/бонус не
    должны ронять флоу регистрации."""
    try:
        db.add(CampaignRegistration(campaign_id=campaign.id, user_id=user.id))

        if campaign.bonus_type == 'balance' and campaign.balance_bonus_kopeks > 0:
            user.balance_kopeks += campaign.balance_bonus_kopeks
            db.add(
                Transaction(
                    user_id=user.id,
                    type='topup',
                    amount_kopeks=campaign.balance_bonus_kopeks,
                    status='completed',
                    description=f'Бонус по кампании «{campaign.name}»',
                )
            )
        elif campaign.bonus_type == 'subscription' and campaign.subscription_duration_days:
            from app.services.subscription_provisioning import provision_or_extend_subscription

            tariff_result = await db.execute(select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id).limit(1))
            tariff = tariff_result.scalar_one_or_none()
            if tariff is not None:
                await provision_or_extend_subscription(
                    db, user=user, tariff=tariff, period_days=campaign.subscription_duration_days
                )
        # bonus_type == 'none' — только атрибуция, ничего не начисляем.

        await db.flush()
    except Exception:
        logger.exception('apply_campaign_bonus упал для campaign_id=%s user_id=%s', campaign.id, user.id)


async def get_campaign_stats(db: AsyncSession, campaign: Campaign) -> dict:
    registrations_count = (
        await db.execute(select(CampaignRegistration).where(CampaignRegistration.campaign_id == campaign.id))
    )
    user_ids = [r.user_id for r in registrations_count.scalars().all()]

    if not user_ids:
        return {
            'registrations_count': 0,
            'paying_count': 0,
            'conversion_percent': 0.0,
            'revenue_kopeks': 0,
        }

    revenue_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount_kopeks), 0), func.count(func.distinct(Transaction.user_id)))
        .where(
            Transaction.user_id.in_(user_ids),
            Transaction.type.in_(REVENUE_TYPES),
            Transaction.status == 'completed',
        )
    )
    revenue_kopeks, paying_count = revenue_result.one()

    return {
        'registrations_count': len(user_ids),
        'paying_count': paying_count,
        'conversion_percent': round(paying_count / len(user_ids) * 100, 1),
        'revenue_kopeks': revenue_kopeks,
    }
