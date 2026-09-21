from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.cabinet.deps import get_current_user
from app.config import settings
from app.database.models import User


async def require_admin(user: User = Depends(get_current_user)) -> User:
    # is_admin в БД синхронизируется с ADMIN_TELEGRAM_IDS только когда человек
    # пишет боту — без второй проверки снятый с .env админ сохранял бы доступ к
    # веб-админке до следующего сообщения боту.
    if not user.is_admin or user.telegram_id not in settings.admin_ids():
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Требуются права администратора')
    return user
