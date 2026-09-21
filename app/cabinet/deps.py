from __future__ import annotations

from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.cabinet.security import decode_access_token
from app.database.database import AsyncSessionLocal
from app.database.models import User
from app.logging_setup import bind_context

_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Требуется авторизация')

    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Невалидный или истёкший токен') from error

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Пользователь не найден')
    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Пользователь заблокирован')

    request.state.user_id = user.id  # для access-лога в HTTP-middleware (контекст endpoint-задачи наружу не виден)
    bind_context(user_id=user.id)
    return user
