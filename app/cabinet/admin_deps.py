from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.cabinet.deps import get_current_user
from app.database.models import User


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Требуются права администратора')
    return user
