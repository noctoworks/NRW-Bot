"""/cabinet/* — HTTP-поверхность Mini App. Бизнес-логика НЕ дублируется: и
покупка/продление, и список тарифов/способов оплаты берутся из
app/handlers/subscription.py — того же кода, что использует бот."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cabinet.deps import get_current_user, get_db
from app.cabinet.schemas import (
    AuthRequest,
    AuthResponse,
    ConnectAppOut,
    ConnectAppsResponse,
    ConnectBlockOut,
    ConnectButtonOut,
    ConnectPlatformOut,
    DashboardResponse,
    DeviceOut,
    GiftPurchaseRequest,
    GiftPurchaseResponse,
    LanguageRequest,
    LanguageResponse,
    PaginatedTransactionsResponse,
    PaymentMethodOut,
    PeriodOut,
    ProfileResponse,
    PromoCodeRequest,
    PromoCodeResponse,
    PurchaseRequest,
    PurchaseResponse,
    ReferralResponse,
    SubscriptionOut,
    TariffResponse,
    TransactionOut,
)
from app.cabinet.security import InitDataError, create_access_token, verify_telegram_init_data
from app.config import settings
from app.database.models import Payment, ReferralEarning, Subscription, Transaction, User
from app.external.remnawave import get_remnawave_client
from app.handlers.gift import PAYMENT_METHODS as GIFT_PAYMENT_METHODS, purchase_gift_subscription
from app.handlers.subscription import (
    PAYMENT_METHODS,
    PERIOD_LABELS,
    InsufficientBalanceError,
    get_active_tariff,
    get_user_subscription,
    purchase_or_renew_subscription,
)
from app.services.pricing_service import apply_discount, get_discount_percent
from app.services.promocode_service import PromoCodeError, activate_promocode
from app.services.referral_service import REFERRAL_MILESTONES, generate_referral_code

router = APIRouter(prefix='/cabinet')

TRANSACTIONS_PAGE_SIZE = 15
GIFT_PAYMENT_METHOD_IDS = {method_id for method_id, _ in GIFT_PAYMENT_METHODS}


def _slugify(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return slug or 'app'


def _resolve_locale(value: dict[str, str], language: str) -> str:
    """locale-словарь ({{"ru": "...", "en": "..."}}) -> строка под язык
    пользователя, с фоллбэком на en, затем на первое, что есть (Subpage
    Builder не гарантирует ru/en для всех кастомных приложений)."""
    return value.get(language) or value.get('en') or next(iter(value.values()), '')


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
    payment_methods = []
    if user.balance_kopeks > 0:
        # Показываем всегда, если баланс вообще не нулевой (а не только если
        # хватает на самый дешёвый период — periods тут несколько, а способ
        # оплаты один список на все сразу) — конкретную нехватку на выбранный
        # период отловит InsufficientBalanceError при попытке покупки.
        payment_methods.append(PaymentMethodOut(id='balance', label=f'💰 Баланс ({user.balance_kopeks / 100:.0f} ₽)'))
    payment_methods += [PaymentMethodOut(id=method_id, label=label) for method_id, label in PAYMENT_METHODS.items()]

    return TariffResponse(name=active_tariff.name, periods=periods, payment_methods=payment_methods)


@router.post('/subscription/purchase', response_model=PurchaseResponse)
async def purchase(
    payload: PurchaseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PurchaseResponse:
    if payload.method != 'balance' and payload.method not in PAYMENT_METHODS:
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
    except InsufficientBalanceError as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f'Недостаточно средств на балансе — не хватает {error.missing_kopeks / 100:.2f} ₽'
        ) from error
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


@router.get('/connect-apps', response_model=ConnectAppsResponse)
async def connect_apps(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> ConnectAppsResponse:
    """Список VPN-клиентов по платформам для кнопки "Подключить VPN" в Mini App —
    берётся из Subpage Builder панели Remnawave (RemnawaveClient.get_subscription_page_config),
    а не хардкодится на фронте (там были непроверенные/неверные url-схемы — см. ревью).
    Плейсхолдеры {{SUBSCRIPTION_LINK}}/{{USERNAME}} в deep-link'ах подставляются
    здесь же, под конкретного пользователя — фронт получает уже готовые ссылки."""
    subscription = await get_user_subscription(db, user.id)
    if subscription is None or not subscription.subscription_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Подписка не найдена')

    config = await get_remnawave_client().get_subscription_page_config()
    if config is None:
        return ConnectAppsResponse(platforms=[])

    # username в Remnawave — всегда tg{telegram_id} (см. RealRemnawaveClient.create_user),
    # отдельно в БД не храним — это просто непрозрачный идентификатор панели.
    substitutions = {
        '{{SUBSCRIPTION_LINK}}': subscription.subscription_url,
        '{{USERNAME}}': f'tg{user.telegram_id}',
    }

    def _apply_template(link: str) -> str:
        for token, value in substitutions.items():
            link = link.replace(token, value)
        return link

    platforms_out: list[ConnectPlatformOut] = []
    for platform in config.platforms:
        apps_out: list[ConnectAppOut] = []
        for app in platform.apps:
            blocks_out = [
                ConnectBlockOut(
                    title=_resolve_locale(block.title, user.language),
                    description=_resolve_locale(block.description, user.language),
                    icon_key=block.icon_key,
                    icon_color=block.icon_color,
                    buttons=[
                        ConnectButtonOut(
                            type=button.type,
                            label=_resolve_locale(button.text, user.language),
                            url=_apply_template(button.link),
                        )
                        for button in block.buttons
                    ],
                )
                for block in app.blocks
            ]
            apps_out.append(
                ConnectAppOut(id=_slugify(app.name), name=app.name, featured=app.featured, blocks=blocks_out)
            )
        platforms_out.append(
            ConnectPlatformOut(
                key=platform.key,
                label=_resolve_locale(platform.display_name, user.language) or platform.key,
                apps=apps_out,
            )
        )

    return ConnectAppsResponse(platforms=platforms_out)


@router.get('/referral', response_model=ReferralResponse)
async def referral(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> ReferralResponse:
    """Реферальная ссылка/статистика для Mini App — то же самое, что показывает
    боту handlers/referral.py::cb_referral_menu (единый источник данных, просто
    другая поверхность отображения)."""
    count_result = await db.execute(select(func.count(User.id)).where(User.referred_by_id == user.id))
    invited_count = count_result.scalar_one() or 0

    sum_result = await db.execute(
        select(func.coalesce(func.sum(ReferralEarning.amount_kopeks), 0)).where(ReferralEarning.user_id == user.id)
    )
    earned_kopeks = sum_result.scalar_one() or 0

    percent = user.referral_commission_percent if user.referral_commission_percent is not None else settings.REFERRAL_PERCENT
    referral_link = f'https://t.me/{settings.BOT_USERNAME}?start=ref_{user.referral_code}' if settings.BOT_USERNAME else ''

    next_milestone_at: int | None = None
    next_milestone_bonus_days: int | None = None
    upcoming = sorted(t for t in REFERRAL_MILESTONES if t > invited_count)
    if upcoming:
        next_milestone_at = upcoming[0]
        next_milestone_bonus_days = REFERRAL_MILESTONES[next_milestone_at]

    return ReferralResponse(
        referral_link=referral_link,
        percent=percent,
        invited_count=invited_count,
        earned_kopeks=earned_kopeks,
        next_milestone_at=next_milestone_at,
        next_milestone_bonus_days=next_milestone_bonus_days,
    )


@router.get('/profile', response_model=ProfileResponse)
async def profile(user: User = Depends(get_current_user)) -> ProfileResponse:
    """Профиль — открывается тапом по имени/аватарке в TopBar. Баланс здесь
    показывается ВПЕРВЫЕ во всём Mini App (раньше /cabinet/dashboard его уже
    отдавал, но фронт нигде не рендерил) — важно при переносе пользователей
    со старого бота: у них уже есть ненулевой balance_kopeks, и он не должен
    быть невидимым в новом интерфейсе."""
    return ProfileResponse(
        telegram_id=user.telegram_id,
        username=user.username,
        full_name=user.full_name,
        language=user.language,
        balance_kopeks=user.balance_kopeks,
        created_at=user.created_at,
    )


@router.get('/transactions', response_model=PaginatedTransactionsResponse)
async def transactions(
    page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> PaginatedTransactionsResponse:
    """История транзакций самого пользователя (пополнения/оплаты/реферальные
    начисления/возвраты) — self-service аналог admin_routes.py::user_transactions,
    но без права смотреть чужие."""
    count_stmt = select(func.count(Transaction.id)).where(Transaction.user_id == user.id)
    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max((total + TRANSACTIONS_PAGE_SIZE - 1) // TRANSACTIONS_PAGE_SIZE, 1)

    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc())
        .limit(TRANSACTIONS_PAGE_SIZE)
        .offset((page - 1) * TRANSACTIONS_PAGE_SIZE)
    )
    items = [
        TransactionOut(
            id=t.id, type=t.type, amount_kopeks=t.amount_kopeks, status=t.status, description=t.description, created_at=t.created_at
        )
        for t in result.scalars().all()
    ]
    return PaginatedTransactionsResponse(items=items, total=total, page=page, total_pages=total_pages)


# === Устройства (живой запрос к Remnawave, ничего не хранится в БД) — self-service
# аналог app/cabinet/admin_routes.py::list_devices/remove_device/reset_devices, но
# только над своими устройствами (без права смотреть/сбрасывать чужие). ==========


@router.get('/devices', response_model=list[DeviceOut])
async def devices(user: User = Depends(get_current_user)) -> list[DeviceOut]:
    if not user.remnawave_uuid:
        return []
    device_list = await get_remnawave_client().get_user_devices(remnawave_uuid=user.remnawave_uuid)
    return [
        DeviceOut(hwid=d.hwid, platform=d.platform, device_model=d.device_model, created_at=d.created_at)
        for d in device_list
    ]


@router.delete('/devices/{hwid}')
async def remove_own_device(hwid: str, user: User = Depends(get_current_user)) -> dict[str, str]:
    if not user.remnawave_uuid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Подписка не найдена')
    await get_remnawave_client().remove_device(remnawave_uuid=user.remnawave_uuid, hwid=hwid)
    return {'status': 'removed'}


@router.delete('/devices')
async def reset_own_devices(user: User = Depends(get_current_user)) -> dict[str, str]:
    if not user.remnawave_uuid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Подписка не найдена')
    await get_remnawave_client().reset_user_devices(remnawave_uuid=user.remnawave_uuid)
    return {'status': 'reset'}


@router.post('/promocode/activate', response_model=PromoCodeResponse)
async def promocode_activate(
    payload: PromoCodeRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> PromoCodeResponse:
    """Тот же activate_promocode, что использует бот в /promo (handlers/promocode.py) —
    бизнес-логика не дублируется, здесь только HTTP-обёртка."""
    try:
        result = await activate_promocode(db, code=payload.code, user=user)
    except PromoCodeError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error

    await db.commit()
    return PromoCodeResponse(type=result.type, value=result.value)


@router.post('/gift/purchase', response_model=GiftPurchaseResponse)
async def gift_purchase(
    payload: GiftPurchaseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GiftPurchaseResponse:
    """Купить подарочную подписку — использует тот же purchase_gift_subscription,
    что и бот (handlers/gift.py::cb_choose_payment). Период/цены берутся из того
    же активного тарифа, что и обычная покупка (см. /cabinet/tariff — общий
    список периодов/способов оплаты подходит и для подарка)."""
    if payload.method not in GIFT_PAYMENT_METHOD_IDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Неизвестный способ оплаты')

    active_tariff = await get_active_tariff(db)
    if active_tariff is None or str(payload.period_days) not in active_tariff.period_prices_kopeks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Недоступный период подписки')

    try:
        gift_code = await purchase_gift_subscription(
            db, user, active_tariff, payload.period_days, payload.method, bot=request.app.state.bot
        )
    except Exception as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, 'Не удалось оформить подарок, попробуйте позже') from error

    await db.commit()

    if gift_code is None:
        payment_result = await db.execute(
            select(Payment)
            .where(Payment.user_id == user.id, Payment.status == 'pending')
            .order_by(Payment.id.desc())
            .limit(1)
        )
        payment = payment_result.scalar_one_or_none()
        payment_url = (payment.raw_payload or {}).get('payment_url') if payment else None
        return GiftPurchaseResponse(status='pending', payment_url=payment_url)

    gift_link = f'https://t.me/{settings.BOT_USERNAME}?start=gift_{gift_code.code}' if settings.BOT_USERNAME else None
    return GiftPurchaseResponse(status='success', gift_link=gift_link)


@router.post('/settings/language', response_model=LanguageResponse)
async def set_language(
    payload: LanguageRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> LanguageResponse:
    """Тот же User.language, что переключает settings:lang: в самом боте
    (handlers/start.py::cb_settings_set_language) — один язык на оба интерфейса."""
    language = payload.language if payload.language in ('ru', 'en') else 'ru'
    user.language = language
    await db.commit()
    return LanguageResponse(language=language)
