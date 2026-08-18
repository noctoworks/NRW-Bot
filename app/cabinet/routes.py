"""/cabinet/* — HTTP-поверхность Mini App. Бизнес-логика НЕ дублируется: и
покупка/продление, и список тарифов/способов оплаты берутся из
app/handlers/subscription.py — того же кода, что использует бот."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cabinet.deps import get_current_user, get_db
from app.cabinet.schemas import (
    AuthRequest,
    AuthResponse,
    DashboardResponse,
    PaymentMethodOut,
    PeriodOut,
    PurchaseRequest,
    PurchaseResponse,
    SubscriptionOut,
    TariffResponse,
)
from app.cabinet.security import InitDataError, create_access_token, verify_telegram_init_data
from app.database.models import Payment, Subscription, User
from app.handlers.subscription import (
    PAYMENT_METHODS,
    PERIOD_LABELS,
    get_active_tariff,
    get_user_subscription,
    purchase_or_renew_subscription,
)
from app.services.pricing_service import apply_discount, get_discount_percent
from app.services.referral_service import generate_referral_code

router = APIRouter(prefix='/cabinet')


async def _generate_unique_referral_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = generate_referral_code()
        result = await db.execute(select(User.id).where(User.referral_code == code))
        if result.scalar_one_or_none() is None:
            return code
    raise RuntimeError('Не удалось сгенерировать уникальный referral_code за 10 попыток')


def _subscription_out(subscription: Subscription | None) -> SubscriptionOut | None:
    if subscription is None:
        return None
    return SubscriptionOut(
        status=subscription.status,
        end_date=subscription.end_date,
        traffic_limit_gb=subscription.traffic_limit_gb,
        traffic_used_gb=subscription.traffic_used_gb,
        device_limit=subscription.device_limit,
        subscription_url=subscription.subscription_url,
    )


@router.post('/auth/telegram', response_model=AuthResponse)
async def auth_telegram(payload: AuthRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    try:
        tg_user = verify_telegram_init_data(payload.init_data)
    except InitDataError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error

    telegram_id = int(tg_user['id'])
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=tg_user.get('username'),
            language=(tg_user.get('language_code') or 'ru')[:2] if (tg_user.get('language_code') or '')[:2] in ('ru', 'en') else 'ru',
            referral_code=await _generate_unique_referral_code(db),
        )
        db.add(user)
        await db.flush()

    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Пользователь заблокирован')

    await db.commit()
    return AuthResponse(access_token=create_access_token(user.id))


@router.get('/dashboard', response_model=DashboardResponse)
async def dashboard(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> DashboardResponse:
    subscription = await get_user_subscription(db, user.id)
    return DashboardResponse(
        balance_kopeks=user.balance_kopeks, subscription=_subscription_out(subscription), is_admin=user.is_admin
    )


@router.get('/tariff', response_model=TariffResponse)
async def tariff(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> TariffResponse:
    active_tariff = await get_active_tariff(db)
    if active_tariff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Тариф временно недоступен')

    discount_percent = await get_discount_percent(db, user)
    periods = [
        PeriodOut(
            days=int(days_str),
            label=PERIOD_LABELS.get(days_str, f'{days_str} дней'),
            price_kopeks=apply_discount(int(price_kopeks), discount_percent),
        )
        for days_str, price_kopeks in sorted(active_tariff.period_prices_kopeks.items(), key=lambda kv: int(kv[0]))
    ]
    payment_methods = [PaymentMethodOut(id=method_id, label=label) for method_id, label in PAYMENT_METHODS.items()]

    return TariffResponse(name=active_tariff.name, periods=periods, payment_methods=payment_methods)


@router.post('/subscription/purchase', response_model=PurchaseResponse)
async def purchase(
    payload: PurchaseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PurchaseResponse:
    if payload.method not in PAYMENT_METHODS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Неизвестный способ оплаты')

    active_tariff = await get_active_tariff(db)
    if active_tariff is None or str(payload.period_days) not in active_tariff.period_prices_kopeks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Недоступный период подписки')

    try:
        subscription = await purchase_or_renew_subscription(
            db,
            user,
            active_tariff,
            period_days=payload.period_days,
            method=payload.method,
            bot=request.app.state.bot,
        )
    except Exception as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, 'Не удалось оформить подписку, попробуйте позже') from error

    await db.commit()

    if subscription is None:
        payment_result = await db.execute(
            select(Payment)
            .where(Payment.user_id == user.id, Payment.status == 'pending')
            .order_by(Payment.id.desc())
            .limit(1)
        )
        payment = payment_result.scalar_one_or_none()
        payment_url = (payment.raw_payload or {}).get('payment_url') if payment else None
        return PurchaseResponse(status='pending', payment_url=payment_url)

    return PurchaseResponse(status='success', subscription=_subscription_out(subscription))
