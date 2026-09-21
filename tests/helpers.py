from __future__ import annotations

from app.database.models import Tariff, User


async def make_user(factory, telegram_id: int = 1, **fields) -> int:
    async with factory() as db:
        user = User(telegram_id=telegram_id, referral_code=fields.pop('referral_code', f'ref{telegram_id}'), **fields)
        db.add(user)
        await db.commit()
        return user.id


async def make_tariff(factory, **fields) -> int:
    defaults = dict(
        name='Test',
        period_prices_kopeks={'30': 10000},
        traffic_limit_gb=0,
        device_limit=3,
        squad_uuids=[],
        is_active=True,
    )
    async with factory() as db:
        tariff = Tariff(**{**defaults, **fields})
        db.add(tariff)
        await db.commit()
        return tariff.id
