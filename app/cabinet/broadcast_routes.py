"""/cabinet/admin/broadcasts/* — рассылки по пользователям из веб-админки. Логика отправки —
в app/services/broadcast_service.py, общая с ботом (app/handlers/admin.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cabinet.admin_deps import require_admin
from app.cabinet.broadcast_schemas import (
    BroadcastButtonOut,
    BroadcastCreateRequest,
    BroadcastListResponse,
    BroadcastOptionsResponse,
    BroadcastOut,
    BroadcastPreviewRequest,
    BroadcastPreviewResponse,
    BroadcastTargetOut,
    BroadcastTariffOut,
)
from app.cabinet.deps import get_db
from app.database.models import BroadcastHistory, Tariff, User
from app.handlers.subscription import get_active_tariffs
from app.services import broadcast_service
from app.services.broadcast_service import (
    ALLOWED_MEDIA_TYPES,
    BROADCAST_BUTTONS,
    BROADCAST_TARGETS,
    BroadcastAlreadyRunningError,
    BroadcastNotFoundError,
    BroadcastNotRunningError,
)

router = APIRouter(prefix='/cabinet/admin/broadcasts')

PAGE_SIZE = 20


async def _valid_target_or_400(db: AsyncSession, target: str) -> None:
    if target in BROADCAST_TARGETS:
        return
    if target.startswith('tariff:'):
        rest = target.split(':', 1)[1]
        if rest.isdigit() and await db.get(Tariff, int(rest)) is not None:
            return
    raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Неизвестная аудитория')


def _to_out(history: BroadcastHistory, target_display_name: str) -> BroadcastOut:
    return BroadcastOut(
        id=history.id,
        status=history.status,
        target_type=history.target_type,
        target_display_name=target_display_name,
        total_count=history.total_count,
        sent_count=history.sent_count,
        failed_count=history.failed_count,
        blocked_count=history.blocked_count,
        has_media=history.has_media,
        media_type=history.media_type,
        admin_name=history.admin_name,
        created_at=history.created_at,
        completed_at=history.completed_at,
    )


@router.get('/options', response_model=BroadcastOptionsResponse)
async def get_options(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> BroadcastOptionsResponse:
    targets = [
        BroadcastTargetOut(key=key, label=label, recipient_count=len(await broadcast_service.target_users(db, key)))
        for key, label in BROADCAST_TARGETS.items()
    ]
    tariffs = [
        BroadcastTariffOut(id=t.id, name=t.name, recipient_count=len(await broadcast_service.target_users(db, f'tariff:{t.id}')))
        for t in await get_active_tariffs(db)
    ]
    buttons = [BroadcastButtonOut(key=key, label=value['text']) for key, value in BROADCAST_BUTTONS.items()]
    return BroadcastOptionsResponse(targets=targets, tariffs=tariffs, buttons=buttons)


@router.post('/preview', response_model=BroadcastPreviewResponse)
async def preview_broadcast(
    payload: BroadcastPreviewRequest, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> BroadcastPreviewResponse:
    await _valid_target_or_400(db, payload.target)
    users = await broadcast_service.target_users(db, payload.target)
    name = await broadcast_service.target_display_name(db, payload.target)
    return BroadcastPreviewResponse(target_display_name=name, recipient_count=len(users))


@router.post('/', response_model=BroadcastOut, status_code=status.HTTP_202_ACCEPTED)
async def create_broadcast(
    payload: BroadcastCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> BroadcastOut:
    await _valid_target_or_400(db, payload.target)
    if payload.media_file_id and payload.media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Недопустимый тип медиа')
    unknown_buttons = set(payload.buttons) - BROADCAST_BUTTONS.keys()
    if unknown_buttons:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f'Неизвестные кнопки: {", ".join(sorted(unknown_buttons))}')
    try:
        history = await broadcast_service.start_broadcast(
            db,
            request.app.state.bot,
            admin=admin,
            target=payload.target,
            text=payload.text,
            media_type=payload.media_type,
            media_file_id=payload.media_file_id,
            selected_buttons=payload.buttons,
        )
    except BroadcastAlreadyRunningError:
        raise HTTPException(status.HTTP_409_CONFLICT, 'Рассылка уже выполняется') from None
    name = await broadcast_service.target_display_name(db, payload.target)
    return _to_out(history, name)


@router.get('/', response_model=BroadcastListResponse)
async def list_broadcasts(
    page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> BroadcastListResponse:
    total = (await db.execute(select(func.count(BroadcastHistory.id)))).scalar_one()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    rows = (
        await db.execute(
            select(BroadcastHistory).order_by(BroadcastHistory.created_at.desc()).limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)
        )
    ).scalars().all()
    items = [_to_out(row, await broadcast_service.target_display_name(db, row.target_type)) for row in rows]
    return BroadcastListResponse(items=items, total=total, page=page, total_pages=total_pages)


@router.get('/{broadcast_id}', response_model=BroadcastOut)
async def get_broadcast(
    broadcast_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> BroadcastOut:
    history = await db.get(BroadcastHistory, broadcast_id)
    if history is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Рассылка не найдена')
    name = await broadcast_service.target_display_name(db, history.target_type)
    return _to_out(history, name)


@router.post('/{broadcast_id}/cancel', status_code=status.HTTP_202_ACCEPTED)
async def cancel_broadcast_route(
    broadcast_id: int, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    try:
        await broadcast_service.cancel_broadcast(db, broadcast_id)
    except BroadcastNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Рассылка не найдена') from None
    except BroadcastNotRunningError:
        raise HTTPException(status.HTTP_409_CONFLICT, 'Рассылка уже завершена') from None
    return {'status': 'cancelling'}
