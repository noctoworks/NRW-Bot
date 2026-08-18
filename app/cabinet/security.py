"""Верификация Telegram WebApp initData (см. §6 clone-architecture.md) и выдача
JWT для Mini App. Без refresh-токена/CABINET_REFRESH_TOKEN — упрощение для
2-экранного MVP (Telegram и так выдаёт свежую initData при каждом открытии
Mini App), см. диалог.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import jwt

from app.config import settings

INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60
ACCESS_TOKEN_TTL_SECONDS = 12 * 60 * 60
JWT_ALGORITHM = 'HS256'


class InitDataError(ValueError):
    """initData отсутствует/подделана/устарела — вызывающий код возвращает 401."""


def verify_telegram_init_data(init_data: str, *, bot_token: str | None = None) -> dict:
    """Возвращает распарсенный `user`-объект (dict) из initData, если подпись
    подлинная и `auth_date` не старше INIT_DATA_MAX_AGE_SECONDS. Бросает
    InitDataError иначе."""
    token = bot_token or settings.BOT_TOKEN
    if not init_data:
        raise InitDataError('initData пустая')

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    data = dict(pairs)

    received_hash = data.pop('hash', None)
    if not received_hash:
        raise InitDataError('initData без hash')

    data_check_string = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))

    secret_key = hmac.new(b'WebAppData', token.encode('utf-8'), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode('utf-8'), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InitDataError('initData: неверная подпись')

    auth_date = data.get('auth_date')
    if not auth_date or (time.time() - int(auth_date)) > INIT_DATA_MAX_AGE_SECONDS:
        raise InitDataError('initData устарела')

    user_raw = data.get('user')
    if not user_raw:
        raise InitDataError('initData без user')

    try:
        return json.loads(user_raw)
    except json.JSONDecodeError as error:
        raise InitDataError('initData: user не JSON') from error


def create_access_token(user_id: int) -> str:
    now = int(time.time())
    payload = {'sub': str(user_id), 'iat': now, 'exp': now + ACCESS_TOKEN_TTL_SECONDS}
    return jwt.encode(payload, settings.CABINET_JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """Возвращает User.id из токена. Бросает jwt.PyJWTError, если токен
    невалиден/истёк — вызывающий код (app/cabinet/deps.py) ловит и отдаёт 401."""
    payload = jwt.decode(token, settings.CABINET_JWT_SECRET, algorithms=[JWT_ALGORITHM])
    return int(payload['sub'])
