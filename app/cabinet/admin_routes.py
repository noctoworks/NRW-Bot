"""/cabinet/admin/* — веб-версия app/handlers/admin.py. Бизнес-правила
портированы 1:1 (баланс, блокировка, сообщение, массбан, удаление-как-
анонимизация) — см. комментарии у каждого роута со ссылкой на исходную
функцию в handlers/admin.py. Аналитика — тонкие обёртки над
app/services/analytics_service.py."""

from __future__ import annotations

from aiogram.exceptions import TelegramForbiddenError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cabinet.admin_deps import require_admin
from app.cabinet.admin_schemas import (
    AdminSubscriptionOut,
    AdminTransactionOut,
    AdminUserDetailResponse,
    AdminUserListItem,
    AdminUserListResponse,
    BalanceAdjustRequest,
    BlockRequest,
    CohortsResponse,
    LtvResponse,
    MassbanRequest,
    MassbanResponse,
    MessageRequest,
    OverviewResponse,
    ReferralFunnelResponse,
    RevenuePointOut,
)
from app.cabinet.deps import get_db
from app.database.models import ReferralEarning, Subscription, Transaction, User
from app.services import analytics_service
from app.services.notification_service import notify_balance_changed

router = APIRouter(prefix='/cabinet/admin')

PAGE_SIZE = 20


# === Аналитика =================================================================


@router.get('/overview', response_model=OverviewResponse)
async def overview(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    return await analytics_service.get_overview(db)


@router.get('/revenue-timeseries', response_model=list[RevenuePointOut])
async def revenue_timeseries(
    days: int = Query(30, ge=1, le=180), db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[dict]:
    return await analytics_service.get_revenue_timeseries(db, days=days)


@router.get('/ltv', response_model=LtvResponse)
async def ltv(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    return await analytics_service.get_ltv(db)


@router.get('/cohorts', response_model=CohortsResponse)
async def cohorts(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    return await analytics_service.get_cohorts(db)


@router.get('/referrals', response_model=ReferralFunnelResponse)
async def referrals(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    return await analytics_service.get_referral_funnel(db)


# === Пользователи ==============================================================

_LIST_FILTERS = {
    'all': None,
    'no_sub': ~User.subscription.has(),  # см. handlers/admin.py::cb_users_inactive
    'blocked': User.is_blocked.is_(True),  # cb_users_blacklist
    'blocked_bot': User.blocked_bot.is_(True),  # cb_users_blocked_bot
}


@router.get('/users', response_model=AdminUserListResponse)
async def list_users(
    query: str | None = None,
    filter: str = 'all',  # noqa: A002 - имя параметра фиксировано контрактом API
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    if filter not in _LIST_FILTERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Неизвестный фильтр')

    # Портировано из handlers/admin.py::_render_users_list (401-436).
    count_stmt = select(func.count(User.id))
    list_stmt = select(User).options(selectinload(User.subscription)).order_by(User.created_at.desc())

    where_clause = _LIST_FILTERS[filter]
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
        list_stmt = list_stmt.where(where_clause)

    if query:
        stripped = query.strip().lstrip('@')
        if stripped.isdigit():
            search_clause = User.telegram_id == int(stripped)
        else:
            search_clause = User.username.ilike(f'%{stripped}%')
        count_stmt = count_stmt.where(search_clause)
        list_stmt = list_stmt.where(search_clause)

    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    users = (await db.execute(list_stmt.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE))).scalars().all()

    items = [
        AdminUserListItem(
            id=u.id,
            telegram_id=u.telegram_id,
            username=u.username,
            is_blocked=u.is_blocked,
            has_active_subscription=bool(u.subscription and u.subscription.status == 'active'),
            last_activity_at=u.last_activity_at,
            created_at=u.created_at,
        )
        for u in users
    ]
    return {'items': items, 'total': total, 'page': page, 'total_pages': total_pages}


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Пользователь не найден')
    return user


@router.get('/users/{user_id}', response_model=AdminUserDetailResponse)
async def user_detail(
    user_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    # Портировано из _render_user_card (537-582) + cb_user_referrals (727-756)
    # + cb_user_transactions (759-778), одним ответом.
    target = await _get_user_or_404(db, user_id)

    sub = (
        await db.execute(select(Subscription).where(Subscription.user_id == target.id))
    ).scalar_one_or_none()

    tx_result = await db.execute(
        select(Transaction).where(Transaction.user_id == target.id).order_by(Transaction.created_at.desc()).limit(15)
    )
    transactions = tx_result.scalars().all()

    invited_count = (
        await db.execute(select(func.count(User.id)).where(User.referred_by_id == target.id))
    ).scalar_one()
    earned = (
        await db.execute(
            select(func.coalesce(func.sum(ReferralEarning.amount_kopeks), 0)).where(
                ReferralEarning.user_id == target.id
            )
        )
    ).scalar_one()

    return {
        'id': target.id,
        'telegram_id': target.telegram_id,
        'username': target.username,
        'language': target.language,
        'is_blocked': target.is_blocked,
        'blocked_bot': target.blocked_bot,
        'balance_kopeks': target.balance_kopeks,
        'created_at': target.created_at,
        'last_activity_at': target.last_activity_at,
        'subscription': AdminSubscriptionOut(
            status=sub.status,
            end_date=sub.end_date,
            traffic_limit_gb=sub.traffic_limit_gb,
            traffic_used_gb=sub.traffic_used_gb,
            device_limit=sub.device_limit,
        )
        if sub
        else None,
        'transactions': [
            AdminTransactionOut(
                id=t.id, type=t.type, amount_kopeks=t.amount_kopeks, status=t.status, description=t.description, created_at=t.created_at
            )
            for t in transactions
        ],
        'referrals_invited_count': invited_count,
        'referrals_earned_kopeks': earned,
    }


@router.post('/users/{user_id}/balance', response_model=AdminUserDetailResponse)
async def adjust_balance(
    user_id: int,
    payload: BalanceAdjustRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    # Портировано из on_admin_balance_input (651-688) — та же формула и тот же
    # клэмп баланса на 0 при списании (не тихий баг, принятое правило бота).
    target = await _get_user_or_404(db, user_id)

    kopeks = round(payload.amount_rub * 100)
    if kopeks == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Сумма не может быть нулевой')

    target.balance_kopeks = max(0, target.balance_kopeks + kopeks)
    db.add(
        Transaction(
            user_id=target.id,
            type='topup' if kopeks > 0 else 'refund',
            amount_kopeks=abs(kopeks),
            status='completed',
            description='Начислено администратором' if kopeks > 0 else 'Списано администратором',
        )
    )
    await db.flush()
    await db.commit()

    await notify_balance_changed(
        request.app.state.bot,
        telegram_id=target.telegram_id,
        amount_kopeks=kopeks,
        new_balance_kopeks=target.balance_kopeks,
    )

    return await user_detail(user_id, db=db, _admin=_admin)


@router.post('/users/{user_id}/block', response_model=AdminUserDetailResponse)
async def toggle_block(
    user_id: int,
    payload: BlockRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    # cb_toggle_block (617-631)
    target = await _get_user_or_404(db, user_id)
    target.is_blocked = payload.blocked
    await db.commit()
    return await user_detail(user_id, db=db, _admin=_admin)


@router.post('/users/{user_id}/message')
async def message_user(
    user_id: int,
    payload: MessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    # on_admin_message_input (703-724)
    target = await _get_user_or_404(db, user_id)
    try:
        await request.app.state.bot.send_message(
            target.telegram_id, f'📩 Сообщение от администрации:\n\n{payload.text}'
        )
    except TelegramForbiddenError:
        target.blocked_bot = True
        await db.commit()
        return {'status': 'blocked_bot'}
    except Exception as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, 'Не удалось отправить сообщение') from error

    return {'status': 'sent'}


@router.post('/users/massban', response_model=MassbanResponse)
async def massban(
    payload: MassbanRequest, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    # on_admin_massban_input (497-513)
    if not payload.telegram_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Список telegram_id пуст')

    result = await db.execute(update(User).where(User.telegram_id.in_(payload.telegram_ids)).values(is_blocked=True))
    await db.commit()
    return {'blocked_count': result.rowcount, 'requested_count': len(payload.telegram_ids)}


@router.delete('/users/{user_id}')
async def delete_user(
    user_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, str]:
    # cb_user_delete_yes (806-818) — анонимизация, НЕ hard delete: финансовая
    # история и рефералы сохраняются для целостности данных.
    target = await _get_user_or_404(db, user_id)
    target.is_blocked = True
    target.username = None
    await db.commit()
    return {'status': 'anonymized'}
