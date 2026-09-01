"""/cabinet/admin/* — веб-версия app/handlers/admin.py. Бизнес-правила
портированы 1:1 (баланс, блокировка, сообщение, массбан, удаление-как-
анонимизация) — см. комментарии у каждого роута со ссылкой на исходную
функцию в handlers/admin.py. Аналитика — тонкие обёртки над
app/services/analytics_service.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramForbiddenError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cabinet.admin_deps import require_admin
from app.cabinet.admin_schemas import (
    AdminSubscriptionListItem,
    AdminSubscriptionOut,
    AdminTransactionDetailResponse,
    AdminTransactionListItem,
    AdminTransactionOut,
    AdminUserDetailResponse,
    AdminUserListItem,
    AdminUserListResponse,
    BalanceAdjustRequest,
    BlockRequest,
    CampaignCreateRequest,
    CampaignOut,
    CampaignStatsResponse,
    CampaignUpdateRequest,
    CohortsResponse,
    DeviceOut,
    LtvResponse,
    MassbanRequest,
    MassbanResponse,
    MessageRequest,
    NodeOut,
    OverviewResponse,
    PaginatedTransactionsResponse,
    PromoGroupCreateRequest,
    PromoGroupOut,
    PromoGroupUpdateRequest,
    RecentPaymentOut,
    ReferralCommissionRequest,
    ReferralFunnelResponse,
    RevenuePointOut,
    SetUserPromoGroupRequest,
    SubscriptionDaysAdjustRequest,
    SupportMessageOut,
    SupportReplyRequest,
    SupportThreadDetailResponse,
    SubscriptionListResponse,
    SupportThreadOut,
    SyncResultResponse,
    TransactionListResponse,
)
from app.cabinet.deps import get_db
from app.config import settings
from app.database.models import (
    Campaign,
    Payment,
    PromoGroup,
    ReferralEarning,
    Subscription,
    SupportMessage,
    SupportTicket,
    Tariff,
    Transaction,
    User,
)
from app.external.remnawave import get_remnawave_client
from app.services import analytics_service, campaign_service
from app.services.notification_service import notify_balance_changed
from app.services.payment import get_payment_provider
from app.services.subscription_provisioning import provision_or_extend_subscription

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


@router.get('/recent-payments', response_model=list[RecentPaymentOut])
async def recent_payments(
    limit: int = Query(10, ge=1, le=50), db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[dict]:
    return await analytics_service.get_recent_payments(db, limit=limit)


@router.get('/nodes', response_model=list[NodeOut])
async def nodes(_admin: User = Depends(require_admin)) -> list[dict]:
    return await get_remnawave_client().list_nodes()


_SUBSCRIPTION_STATUSES = {'active', 'expired', 'disabled'}


@router.get('/subscriptions', response_model=SubscriptionListResponse)
async def list_subscriptions(
    query: str | None = None,
    status_filter: str | None = Query(None, alias='status'),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    """Подписки по ВСЕМ пользователям (см. диалог 2026-09-01) — только наши
    данные (Subscription join Tariff/User), никаких обращений к Remnawave —
    тот же паттерн поиска/фильтра/пагинации, что list_users/list_transactions
    выше."""
    if status_filter is not None and status_filter not in _SUBSCRIPTION_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Неизвестный статус подписки')

    count_stmt = select(func.count(Subscription.id)).select_from(Subscription).join(User, User.id == Subscription.user_id)
    list_stmt = (
        select(Subscription, User, Tariff)
        .join(User, User.id == Subscription.user_id)
        .join(Tariff, Tariff.id == Subscription.tariff_id)
        .order_by(Subscription.end_date.desc())
    )

    if status_filter is not None:
        count_stmt = count_stmt.where(Subscription.status == status_filter)
        list_stmt = list_stmt.where(Subscription.status == status_filter)
    if query:
        stripped = query.strip().lstrip('@')
        search_clause = User.telegram_id == int(stripped) if stripped.isdigit() else User.username.ilike(f'%{stripped}%')
        count_stmt = count_stmt.where(search_clause)
        list_stmt = list_stmt.where(search_clause)

    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    rows = (await db.execute(list_stmt.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE))).all()

    items = [
        AdminSubscriptionListItem(
            user_id=u.id,
            telegram_id=u.telegram_id,
            username=u.username,
            full_name=u.full_name,
            tariff_name=tf.name,
            status=s.status,
            is_trial=s.is_trial,
            end_date=s.end_date,
            traffic_used_gb=s.traffic_used_gb,
            traffic_limit_gb=s.traffic_limit_gb,
            device_limit=s.device_limit,
            autopay_enabled=s.autopay_enabled,
        )
        for s, u, tf in rows
    ]
    return {'items': items, 'total': total, 'page': page, 'total_pages': total_pages}


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
            full_name=u.full_name,
            is_blocked=u.is_blocked,
            has_active_subscription=bool(u.subscription and u.subscription.status == 'active'),
            is_trial=bool(u.subscription and u.subscription.status == 'active' and u.subscription.is_trial),
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
        'full_name': target.full_name,
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
            is_trial=sub.is_trial,
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
        'referral_commission_percent': target.referral_commission_percent,
        'promo_group_id': target.promo_group_id,
        'promo_group_name': (await db.get(PromoGroup, target.promo_group_id)).name if target.promo_group_id else None,
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

    new_balance = max(0, target.balance_kopeks + kopeks)
    # Реально применённая сумма ПОСЛЕ клэмпа — не запрошенная kopeks. Иначе
    # списание больше, чем есть на балансе, пишет в Transaction и в уведомление
    # юзеру завышенную сумму, хотя баланс упал только до 0 (см. ревью).
    applied_kopeks = new_balance - target.balance_kopeks
    if applied_kopeks == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Баланс уже равен 0 — списывать нечего')

    target.balance_kopeks = new_balance
    db.add(
        Transaction(
            user_id=target.id,
            type='topup' if applied_kopeks > 0 else 'refund',
            amount_kopeks=abs(applied_kopeks),
            status='completed',
            description='Начислено администратором' if applied_kopeks > 0 else 'Списано администратором',
        )
    )
    await db.flush()
    await db.commit()

    await notify_balance_changed(
        request.app.state.bot,
        telegram_id=target.telegram_id,
        amount_kopeks=applied_kopeks,
        new_balance_kopeks=target.balance_kopeks,
    )

    return await user_detail(user_id, db=db, _admin=_admin)


@router.post('/users/{user_id}/subscription-days', response_model=AdminUserDetailResponse)
async def adjust_subscription_days(
    user_id: int,
    payload: SubscriptionDaysAdjustRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    """Продлить (days > 0) или сократить (days < 0) действующую подписку —
    веб-аналог handlers/admin.py::cb_user_grant_sub, но произвольным числом
    дней вместо фиксированных периодов тарифа, и умеет сокращать (то, чего
    в боте нет вообще).

    is_trial подписки НЕ трогаем — ручная правка срока админом (в обе стороны)
    не делает пользователя ни "оплатившим", ни "триальщиком" сама по себе,
    см. models.py::Subscription.is_trial и services/subscription_provisioning.py.
    """
    target = await _get_user_or_404(db, user_id)
    if payload.days == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Число дней не может быть нулевым')

    sub = (await db.execute(select(Subscription).where(Subscription.user_id == target.id))).scalar_one_or_none()
    client = get_remnawave_client()
    now = datetime.now(timezone.utc)

    if sub is None:
        if payload.days < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'У пользователя нет подписки — сокращать нечего')
        from app.handlers.subscription import get_active_tariff  # см. диалог о ленивом импорте

        tariff = await get_active_tariff(db)
        if tariff is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Нет активного тарифа для выдачи подписки')
        await provision_or_extend_subscription(db, user=target, tariff=tariff, period_days=payload.days, is_trial=False)
    else:
        base = sub.end_date if sub.end_date.tzinfo else sub.end_date.replace(tzinfo=timezone.utc)
        new_end = base + timedelta(days=payload.days)

        if target.remnawave_uuid:
            await client.extend_user_expiration(remnawave_uuid=target.remnawave_uuid, expire_at=new_end)
            if new_end > now:
                await client.enable_user(remnawave_uuid=target.remnawave_uuid)
            else:
                await client.disable_user(remnawave_uuid=target.remnawave_uuid)

        sub.end_date = new_end
        sub.status = 'active' if new_end > now else 'expired'
        sub.reminder_3d_sent = False
        sub.reminder_1d_sent = False

    await db.commit()
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


async def _get_ticket_or_404(db: AsyncSession, ticket_id: int) -> SupportTicket:
    ticket = await db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Тикет не найден')
    return ticket


@router.get('/support/threads', response_model=list[SupportThreadOut])
async def support_threads(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> list[dict]:
    # Тред = тикет (см. app/database/models.py::SupportTicket, редизайн из MVP,
    # где тредом была неявная группировка SupportMessage по user_id).
    last_ids = select(func.max(SupportMessage.id)).group_by(SupportMessage.ticket_id).scalar_subquery()
    result = await db.execute(
        select(SupportMessage, SupportTicket, User)
        .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
        .join(User, User.id == SupportTicket.user_id)
        .where(SupportMessage.id.in_(last_ids))
        .order_by(SupportMessage.created_at.desc())
    )
    return [
        {
            'ticket_id': ticket.id,
            'status': ticket.status,
            'assigned_admin_name': ticket.assigned_admin_name,
            'user_id': user.id,
            'telegram_id': user.telegram_id,
            'username': user.username,
            'full_name': user.full_name,
            'last_message': msg.body,
            'last_message_at': msg.created_at,
            # direction == 'in' и это последнее сообщение в треде => админ ещё
            # не ответил после него — простая эвристика без отдельного поля "прочитано".
            'unread': msg.direction == 'in',
        }
        for msg, ticket, user in result.all()
    ]


@router.get('/support/threads/{ticket_id}', response_model=SupportThreadDetailResponse)
async def support_thread_detail(
    ticket_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    ticket = await _get_ticket_or_404(db, ticket_id)
    user = await _get_user_or_404(db, ticket.user_id)
    result = await db.execute(
        select(SupportMessage).where(SupportMessage.ticket_id == ticket_id).order_by(SupportMessage.id)
    )
    messages = [
        SupportMessageOut(id=m.id, direction=m.direction, body=m.body, created_at=m.created_at)
        for m in result.scalars().all()
    ]
    return {
        'ticket_id': ticket.id,
        'status': ticket.status,
        'assigned_admin_name': ticket.assigned_admin_name,
        'user_id': user.id,
        'telegram_id': user.telegram_id,
        'username': user.username,
        'full_name': user.full_name,
        'messages': messages,
    }


@router.post('/support/threads/{ticket_id}/reply')
async def support_thread_reply(
    ticket_id: int,
    payload: SupportReplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    # Тот же способ доставки, что у on_admin_reply (app/handlers/support.py) —
    # роутинг через reply_to_message там не нужен, отвечаем сразу по user_id.
    ticket = await _get_ticket_or_404(db, ticket_id)
    target = await _get_user_or_404(db, ticket.user_id)
    try:
        await request.app.state.bot.send_message(target.telegram_id, f'💬 Ответ поддержки:\n\n{payload.text}')
    except TelegramForbiddenError:
        target.blocked_bot = True
        await db.commit()
        return {'status': 'blocked_bot'}
    except Exception as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, 'Не удалось отправить сообщение') from error

    db.add(SupportMessage(ticket_id=ticket.id, user_id=target.id, direction='out', body=payload.text))
    # Первый ответивший из MiniApp тоже "застолбливает" тикет — тот же паттерн
    # claim, что у on_admin_reply в боте, чтобы бот-часть видела, кто уже ведёт.
    if ticket.assigned_admin_id is None and ticket.assigned_admin_name is None:
        ticket.assigned_admin_id = _admin.id
        ticket.assigned_admin_name = _admin.username or str(_admin.telegram_id)
    await db.commit()
    return {'status': 'sent'}


@router.post('/support/threads/{ticket_id}/close')
async def support_thread_close(
    ticket_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, str]:
    ticket = await _get_ticket_or_404(db, ticket_id)
    ticket.status = 'closed'
    ticket.closed_at = datetime.now(timezone.utc)
    await db.commit()
    return {'status': 'closed'}


@router.post('/support/threads/{ticket_id}/reopen')
async def support_thread_reopen(
    ticket_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, str]:
    ticket = await _get_ticket_or_404(db, ticket_id)
    ticket.status = 'open'
    ticket.closed_at = None
    await db.commit()
    return {'status': 'open'}


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


_TRANSACTION_TYPES = {'topup', 'subscription_payment', 'referral_reward', 'refund', 'gift'}
_TRANSACTION_STATUSES = {'pending', 'completed', 'failed'}


@router.get('/transactions', response_model=TransactionListResponse)
async def list_transactions(
    query: str | None = None,
    type: str | None = None,  # noqa: A002 - имя параметра фиксировано контрактом API
    # alias, а не просто `status: str | None` — так называется параметр в
    # HTTPException/status.HTTP_400_BAD_REQUEST) ниже. Внешний контракт API
    # (?status=) не меняется, alias подменяет только имя Python-переменной.
    status_filter: str | None = Query(None, alias='status'),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    """Транзакции по ВСЕМ пользователям (см. диалог 2026-09-01) — раньше
    список был только внутри карточки одного юзера (user_transactions ниже,
    тот же PAGE_SIZE/паттерн пагинации, здесь плюс поиск/фильтры, портировано
    из list_users выше)."""
    if type is not None and type not in _TRANSACTION_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Неизвестный тип транзакции')
    if status_filter is not None and status_filter not in _TRANSACTION_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Неизвестный статус транзакции')

    count_stmt = select(func.count(Transaction.id)).select_from(Transaction).join(User, User.id == Transaction.user_id)
    # outerjoin (не join) — не у каждой транзакции есть Payment (топап админом/
    # реферальный бонус ничего провайдеру не платят, см. AdminTransactionListItem).
    list_stmt = (
        select(Transaction, User, Payment)
        .join(User, User.id == Transaction.user_id)
        .outerjoin(Payment, Payment.transaction_id == Transaction.id)
        .order_by(Transaction.created_at.desc())
    )

    if type is not None:
        count_stmt = count_stmt.where(Transaction.type == type)
        list_stmt = list_stmt.where(Transaction.type == type)
    if status_filter is not None:
        count_stmt = count_stmt.where(Transaction.status == status_filter)
        list_stmt = list_stmt.where(Transaction.status == status_filter)
    if query:
        stripped = query.strip().lstrip('@')
        search_clause = User.telegram_id == int(stripped) if stripped.isdigit() else User.username.ilike(f'%{stripped}%')
        count_stmt = count_stmt.where(search_clause)
        list_stmt = list_stmt.where(search_clause)

    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    rows = (await db.execute(list_stmt.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE))).all()

    items = [
        AdminTransactionListItem(
            id=t.id,
            type=t.type,
            amount_kopeks=t.amount_kopeks,
            status=t.status,
            description=t.description,
            created_at=t.created_at,
            user_id=u.id,
            telegram_id=u.telegram_id,
            username=u.username,
            full_name=u.full_name,
            payment_provider=p.provider if p is not None else None,
            payment_external_id=p.external_id if p is not None else None,
        )
        for t, u, p in rows
    ]
    return {'items': items, 'total': total, 'page': page, 'total_pages': total_pages}


@router.get('/transactions/platega-reconcile', response_model=dict[str, str])
async def platega_reconcile(
    days: int = Query(7, ge=1, le=31), _admin: User = Depends(require_admin)
) -> dict[str, str]:
    """Сверка с личным кабинетом Platega (см. диалог 2026-09-01, "решить вопрос
    по транзакциям, я хочу их видеть" — нашли эндпоинт по их документации,
    POST /transaction/export/json, не было в коде раньше). Возвращает
    {recordId: status} за последние `days` — фронт сопоставляет по
    AdminTransactionListItem.payment_external_id (строки с provider!='platega'
    не сверяются вообще, у них нет external_id в этом пространстве). Лимит 31
    день — реальный запрос к платёжному провайдеру с реальными боевыми
    ключами, не листаем произвольно широкий диапазон по требованию фронта.
    """
    provider = get_payment_provider('platega')
    if not hasattr(provider, 'export_transactions'):
        # PAYMENTS_MODE=stub (см. get_payment_provider) — сверять нечего,
        # это не ошибка конфигурации, а ожидаемое состояние дев/тест-окружений.
        return {}
    since = datetime.now(timezone.utc) - timedelta(days=days)
    until = datetime.now(timezone.utc)
    records = await provider.export_transactions(since=since, until=until)
    return {r['recordId']: r['status'] for r in records if r.get('recordId')}


# ВАЖНО: должен идти ПОСЛЕ /transactions/platega-reconcile выше — Starlette
# матчит роуты в порядке регистрации, и {transaction_id}: int, стоящий раньше,
# перехватил бы "platega-reconcile" как невалидный int (422) вместо того,
# чтобы дать сработать точному роуту (см. диалог 2026-09-01).
@router.get('/transactions/{transaction_id}', response_model=AdminTransactionDetailResponse)
async def transaction_detail(
    transaction_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    """«Тело транзакции» по клику на строку в /transactions (см. диалог
    2026-09-01) — то же, что в списке, плюс Payment.raw_payload/
    provider_raw_response, если у транзакции вообще есть Payment."""
    row = (
        await db.execute(
            select(Transaction, User, Payment)
            .join(User, User.id == Transaction.user_id)
            .outerjoin(Payment, Payment.transaction_id == Transaction.id)
            .where(Transaction.id == transaction_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Транзакция не найдена')
    t, u, p = row
    return {
        'id': t.id,
        'type': t.type,
        'amount_kopeks': t.amount_kopeks,
        'status': t.status,
        'description': t.description,
        'created_at': t.created_at,
        'user_id': u.id,
        'telegram_id': u.telegram_id,
        'username': u.username,
        'full_name': u.full_name,
        'payment_provider': p.provider if p is not None else None,
        'payment_external_id': p.external_id if p is not None else None,
        'payment_status': p.status if p is not None else None,
        'payment_raw_payload': p.raw_payload if p is not None else None,
        'provider_raw_response': p.provider_raw_response if p is not None else None,
    }


@router.get('/users/{user_id}/transactions', response_model=PaginatedTransactionsResponse)
async def user_transactions(
    user_id: int,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    await _get_user_or_404(db, user_id)

    count_stmt = select(func.count(Transaction.id)).where(Transaction.user_id == user_id)
    total = (await db.execute(count_stmt)).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)

    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc())
        .limit(PAGE_SIZE)
        .offset((page - 1) * PAGE_SIZE)
    )
    items = [
        AdminTransactionOut(
            id=t.id, type=t.type, amount_kopeks=t.amount_kopeks, status=t.status, description=t.description, created_at=t.created_at
        )
        for t in result.scalars().all()
    ]
    return {'items': items, 'total': total, 'page': page, 'total_pages': total_pages}


@router.post('/users/{user_id}/referral-commission', response_model=AdminUserDetailResponse)
async def set_referral_commission(
    user_id: int,
    payload: ReferralCommissionRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    target = await _get_user_or_404(db, user_id)
    target.referral_commission_percent = payload.commission_percent
    await db.commit()
    return await user_detail(user_id, db=db, _admin=_admin)


# === Устройства (живой запрос к Remnawave, ничего не хранится в БД — см. §5
# clone-architecture.md) ========================================================


@router.get('/users/{user_id}/devices', response_model=list[DeviceOut])
async def list_devices(
    user_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[dict]:
    target = await _get_user_or_404(db, user_id)
    if not target.remnawave_uuid:
        return []

    devices = await get_remnawave_client().get_user_devices(remnawave_uuid=target.remnawave_uuid)
    return [
        {'hwid': d.hwid, 'platform': d.platform, 'device_model': d.device_model, 'created_at': d.created_at}
        for d in devices
    ]


@router.delete('/users/{user_id}/devices/{hwid}')
async def remove_device(
    user_id: int, hwid: str, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, str]:
    target = await _get_user_or_404(db, user_id)
    if not target.remnawave_uuid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'У пользователя нет активной подписки в Remnawave')
    await get_remnawave_client().remove_device(remnawave_uuid=target.remnawave_uuid, hwid=hwid)
    return {'status': 'removed'}


@router.delete('/users/{user_id}/devices')
async def reset_devices(
    user_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, str]:
    target = await _get_user_or_404(db, user_id)
    if not target.remnawave_uuid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'У пользователя нет активной подписки в Remnawave')
    await get_remnawave_client().reset_user_devices(remnawave_uuid=target.remnawave_uuid)
    return {'status': 'reset'}


# === Синхронизация с Remnawave =================================================


@router.post('/users/{user_id}/sync/from-panel', response_model=SyncResultResponse)
async def sync_from_panel(
    user_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    """Панель — источник истины: подтягиваем трафик/срок/статус в БД."""
    target = await _get_user_or_404(db, user_id)
    if not target.remnawave_uuid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'У пользователя нет remnawave_uuid')

    sub = (await db.execute(select(Subscription).where(Subscription.user_id == target.id))).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'У пользователя нет подписки в БД')

    remote = await get_remnawave_client().get_subscription_info(remnawave_uuid=target.remnawave_uuid)
    sub.traffic_used_gb = remote.traffic_used_gb
    if remote.expire_at is not None:
        sub.end_date = remote.expire_at
    sub.status = 'active' if remote.is_enabled else 'disabled'
    await db.commit()

    return {
        'status': 'synced',
        'subscription': AdminSubscriptionOut(
            status=sub.status,
            end_date=sub.end_date,
            traffic_limit_gb=sub.traffic_limit_gb,
            traffic_used_gb=sub.traffic_used_gb,
            device_limit=sub.device_limit,
        ),
    }


@router.post('/users/{user_id}/sync/to-panel', response_model=SyncResultResponse)
async def sync_to_panel(
    user_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    """БД — источник истины: прописываем срок/статус в панель."""
    target = await _get_user_or_404(db, user_id)
    if not target.remnawave_uuid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'У пользователя нет remnawave_uuid')

    sub = (await db.execute(select(Subscription).where(Subscription.user_id == target.id))).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'У пользователя нет подписки в БД')

    client = get_remnawave_client()
    end_date = sub.end_date if sub.end_date.tzinfo else sub.end_date.replace(tzinfo=timezone.utc)
    tariff = await db.get(Tariff, sub.tariff_id)
    await client.extend_user_expiration(
        remnawave_uuid=target.remnawave_uuid,
        expire_at=end_date,
        traffic_limit_gb=sub.traffic_limit_gb,
        squad_uuids=tariff.squad_uuids if tariff else None,
    )
    if sub.status == 'active' and end_date > datetime.now(timezone.utc):
        await client.enable_user(remnawave_uuid=target.remnawave_uuid)
    else:
        await client.disable_user(remnawave_uuid=target.remnawave_uuid)

    return {
        'status': 'synced',
        'subscription': AdminSubscriptionOut(
            status=sub.status,
            end_date=sub.end_date,
            traffic_limit_gb=sub.traffic_limit_gb,
            traffic_used_gb=sub.traffic_used_gb,
            device_limit=sub.device_limit,
        ),
    }


# === Промогруппы (скидочные тиры, см. app/services/pricing_service.py) ========


@router.get('/promo-groups', response_model=list[PromoGroupOut])
async def list_promo_groups(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[dict]:
    groups = (await db.execute(select(PromoGroup).order_by(PromoGroup.id))).scalars().all()
    result = []
    for g in groups:
        users_count = (
            await db.execute(select(func.count(User.id)).where(User.promo_group_id == g.id))
        ).scalar_one()
        result.append({'id': g.id, 'name': g.name, 'discount_percent': g.discount_percent, 'users_count': users_count})
    return result


@router.post('/promo-groups', response_model=PromoGroupOut)
async def create_promo_group(
    payload: PromoGroupCreateRequest, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    group = PromoGroup(name=payload.name, discount_percent=payload.discount_percent)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return {'id': group.id, 'name': group.name, 'discount_percent': group.discount_percent, 'users_count': 0}


async def _get_promo_group_or_404(db: AsyncSession, group_id: int) -> PromoGroup:
    group = await db.get(PromoGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Промогруппа не найдена')
    return group


@router.patch('/promo-groups/{group_id}', response_model=PromoGroupOut)
async def update_promo_group(
    group_id: int,
    payload: PromoGroupUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    group = await _get_promo_group_or_404(db, group_id)
    if payload.name is not None:
        group.name = payload.name
    if payload.discount_percent is not None:
        group.discount_percent = payload.discount_percent
    await db.commit()

    users_count = (
        await db.execute(select(func.count(User.id)).where(User.promo_group_id == group.id))
    ).scalar_one()
    return {'id': group.id, 'name': group.name, 'discount_percent': group.discount_percent, 'users_count': users_count}


@router.delete('/promo-groups/{group_id}')
async def delete_promo_group(
    group_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, str]:
    group = await _get_promo_group_or_404(db, group_id)
    await db.delete(group)
    await db.commit()  # users.promo_group_id -> NULL автоматически (ondelete='SET NULL')
    return {'status': 'deleted'}


@router.post('/users/{user_id}/promo-group', response_model=AdminUserDetailResponse)
async def set_user_promo_group(
    user_id: int,
    payload: SetUserPromoGroupRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    target = await _get_user_or_404(db, user_id)
    if payload.promo_group_id is not None:
        await _get_promo_group_or_404(db, payload.promo_group_id)
    target.promo_group_id = payload.promo_group_id
    await db.commit()
    return await user_detail(user_id, db=db, _admin=_admin)


# === Кампании (маркетинговая атрибуция, см. app/services/campaign_service.py) =


def _campaign_out(campaign: Campaign) -> dict:
    bot_username = settings.BOT_USERNAME or '<укажите_BOT_USERNAME>'
    return {
        'id': campaign.id,
        'name': campaign.name,
        'start_parameter': campaign.start_parameter,
        'bonus_type': campaign.bonus_type,
        'balance_bonus_kopeks': campaign.balance_bonus_kopeks,
        'subscription_duration_days': campaign.subscription_duration_days,
        'is_active': campaign.is_active,
        'deep_link': f'https://t.me/{bot_username}?start={campaign.start_parameter}',
    }


@router.get('/campaigns', response_model=list[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> list[dict]:
    campaigns = (await db.execute(select(Campaign).order_by(Campaign.id.desc()))).scalars().all()
    return [_campaign_out(c) for c in campaigns]


@router.post('/campaigns', response_model=CampaignOut)
async def create_campaign(
    payload: CampaignCreateRequest, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    existing = (
        await db.execute(select(Campaign.id).where(Campaign.start_parameter == payload.start_parameter))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'start_parameter уже занят другой кампанией')

    campaign = Campaign(
        name=payload.name,
        start_parameter=payload.start_parameter,
        bonus_type=payload.bonus_type,
        balance_bonus_kopeks=payload.balance_bonus_kopeks,
        subscription_duration_days=payload.subscription_duration_days,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return _campaign_out(campaign)


async def _get_campaign_or_404(db: AsyncSession, campaign_id: int) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Кампания не найдена')
    return campaign


@router.patch('/campaigns/{campaign_id}', response_model=CampaignOut)
async def update_campaign(
    campaign_id: int,
    payload: CampaignUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    campaign = await _get_campaign_or_404(db, campaign_id)
    if payload.name is not None:
        campaign.name = payload.name
    if payload.is_active is not None:
        campaign.is_active = payload.is_active
    if payload.balance_bonus_kopeks is not None:
        campaign.balance_bonus_kopeks = payload.balance_bonus_kopeks
    if payload.subscription_duration_days is not None:
        campaign.subscription_duration_days = payload.subscription_duration_days
    await db.commit()
    await db.refresh(campaign)
    return _campaign_out(campaign)


@router.delete('/campaigns/{campaign_id}')
async def delete_campaign(
    campaign_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, str]:
    campaign = await _get_campaign_or_404(db, campaign_id)
    await db.delete(campaign)
    await db.commit()
    return {'status': 'deleted'}


@router.get('/campaigns/{campaign_id}/stats', response_model=CampaignStatsResponse)
async def campaign_stats(
    campaign_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    campaign = await _get_campaign_or_404(db, campaign_id)
    return await campaign_service.get_campaign_stats(db, campaign)
