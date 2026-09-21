"""/cabinet/admin/notifications/* — редактирование текстов автоматических сообщений бота."""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.emoji as emoji_module
from app.cabinet.admin_deps import require_admin
from app.cabinet.deps import get_db
from app.cabinet.notifications_schemas import (
    EmojiOut,
    PreviewRequest,
    PreviewResponse,
    TemplateOut,
    TemplateUpdateRequest,
    VariableDocOut,
)
from app.config import settings
from app.database.models import MessageTemplate, User
from app.services.message_templates.registry import EVENTS, EventDef, UnknownEventError, get_event
from app.services.message_templates.service import (
    TemplateValidationError,
    build_preview,
    reset_template,
    send_test_message,
    update_template,
)
from app.services.message_templates.validation import validate_button_text, validate_template

router = APIRouter(prefix='/cabinet/admin/notifications')


def _event_or_404(key: str) -> EventDef:
    try:
        return get_event(key)
    except UnknownEventError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Событие не найдено') from None


def _unprocessable(errors: list[str]) -> HTTPException:
    detail = [{'loc': ['body'], 'msg': message, 'type': 'template_invalid'} for message in errors]
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


def _author_name(user: User | None) -> str | None:
    if user is None:
        return None
    return user.username or user.full_name or str(user.telegram_id)


def _to_out(event: EventDef, row: MessageTemplate | None, author: User | None) -> TemplateOut:
    miniapp = bool(settings.MINIAPP_URL)
    default_button = event.button_label(miniapp)
    customised = row is not None and row.template is not None
    button = None
    if event.has_button:
        button = row.button_text if row is not None and row.button_text else default_button
    return TemplateOut(
        key=event.key,
        group=event.group,
        title=event.title,
        trigger=event.trigger,
        template=row.template if customised else event.default_template,  # type: ignore[union-attr]
        variables=list(event.variable_names),
        default_template=event.default_template,
        is_customized=customised,
        enabled=row.enabled if row is not None else True,
        button_text=button,
        default_button_text=default_button,
        variable_docs=[VariableDocOut(name=v.name, description=v.description, example=v.example) for v in event.variables],
        required_variables=list(event.required_variables),
        updated_at=row.updated_at if row is not None else None,
        updated_by=_author_name(author),
    )


async def _load_all(db: AsyncSession) -> list[TemplateOut]:
    rows = {row.key: row for row in (await db.execute(select(MessageTemplate))).scalars()}
    author_ids = {row.updated_by_user_id for row in rows.values() if row.updated_by_user_id is not None}
    authors: dict[int, User] = {}
    if author_ids:
        authors = {user.id: user for user in (await db.execute(select(User).where(User.id.in_(author_ids)))).scalars()}
    return [
        _to_out(event, rows.get(event.key), authors.get(rows[event.key].updated_by_user_id) if event.key in rows else None)
        for event in EVENTS
    ]


async def _load_one(db: AsyncSession, key: str) -> TemplateOut:
    return next(item for item in await _load_all(db) if item.key == key)


@router.get('/templates', response_model=list[TemplateOut])
async def list_templates(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> list[TemplateOut]:
    return await _load_all(db)


@router.put('/templates/{key}', response_model=TemplateOut)
async def put_template(
    key: str,
    payload: TemplateUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> TemplateOut:
    _event_or_404(key)
    fields = {}
    if 'template' in payload.model_fields_set:
        fields['template'] = payload.template
    if 'button_text' in payload.model_fields_set:
        fields['button_text'] = payload.button_text
    if payload.enabled is not None:
        fields['enabled'] = payload.enabled
    try:
        await update_template(db, key, admin_user_id=admin.id, **fields)
    except TemplateValidationError as error:
        raise _unprocessable(error.errors) from error
    await db.commit()
    return await _load_one(db, key)


@router.delete('/templates/{key}')
async def delete_template(
    key: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    _event_or_404(key)
    existed = await reset_template(db, key, admin_user_id=admin.id)
    await db.commit()
    return {'status': 'reset', 'was_customized': existed}


async def _validated_preview(db: AsyncSession, key: str, event: EventDef, payload: PreviewRequest):
    """Проверяет текст и подпись (те же правила, что при сохранении) и собирает рендер с примерами."""
    errors: list[str] = []
    result = None
    if payload.template is not None:
        result = validate_template(event, payload.template)
        errors += result.errors
    if payload.button_text is not None:
        errors += validate_button_text(event, payload.button_text)
    if errors:
        raise _unprocessable(errors)
    rendered = await build_preview(key, template=payload.template, button_text=payload.button_text)
    if result is None:  # текущий текст: считаем длину и предупреждения по нему
        current = next(item for item in await _load_all(db) if item.key == key)
        result = validate_template(event, current.template)
    return rendered, result


@router.post('/templates/{key}/preview', response_model=PreviewResponse)
async def preview_template(
    key: str, payload: PreviewRequest, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> PreviewResponse:
    event = _event_or_404(key)
    rendered, result = await _validated_preview(db, key, event, payload)
    return PreviewResponse(
        html=rendered.text, visible_length=result.visible_length, warnings=result.warnings, button_text=rendered.button_text
    )


@router.post('/templates/{key}/test')
async def test_template(
    key: str,
    payload: PreviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Отправляет предпросмотр (с примерами переменных) вызвавшему админу в Telegram."""
    event = _event_or_404(key)
    await _validated_preview(db, key, event, payload)
    try:
        await send_test_message(
            request.app.state.bot, telegram_id=admin.telegram_id, key=key,
            template=payload.template, button_text=payload.button_text,
        )
    except TelegramBadRequest as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f'Telegram отклонил сообщение: {error.message}') from error
    except Exception as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, 'Не удалось отправить тестовое сообщение') from error
    return {'status': 'sent'}


@router.get('/emoji', response_model=list[EmojiOut])
async def list_emoji(_admin: User = Depends(require_admin)) -> list[EmojiOut]:
    """Кастомные эмодзи из app/emoji.py с заданным custom_id — для вставки в текст через <tg-emoji emoji-id="…">."""
    slots = [
        EmojiOut(name=name, fallback=value.fallback, custom_id=value.custom_id)
        for name, value in sorted(vars(emoji_module).items())
        if isinstance(value, emoji_module.Emoji) and value.custom_id
    ]
    return slots
