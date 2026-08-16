"""Разовый сид: один тариф + сквады из Remnawave (мок или реальный — не важно, интерфейс один).

Цены — ПЛЕЙСХОЛДЕРЫ, бизнес-решение по факту не зафиксировано в архитектурном
документе. Поменять их можно тут же или потом через админку (handlers/admin.py,
AdminTariffStates) — таблица TARIFF на это рассчитана с самого начала.

Запуск: .venv\\Scripts\\python.exe scripts\\seed.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database.database import AsyncSessionLocal
from app.database.models import ServerSquad, Tariff
from app.external.remnawave import get_remnawave_client

PLACEHOLDER_PERIOD_PRICES_KOPEKS = {
    '30': 9900,
    '90': 24900,
    '180': 44900,
    '360': 79900,
}


async def seed() -> None:
    client = get_remnawave_client()
    squads = await client.list_internal_squads()

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(Tariff))).scalars().first()
        if existing is None:
            tariff = Tariff(
                name='Standard',
                period_prices_kopeks=PLACEHOLDER_PERIOD_PRICES_KOPEKS,
                traffic_limit_gb=0,  # безлимит
                device_limit=3,
                squad_uuids=[s['uuid'] for s in squads],
                is_active=True,
            )
            db.add(tariff)
            print(f'Создан тариф "Standard" с плейсхолдер-ценами: {PLACEHOLDER_PERIOD_PRICES_KOPEKS}')
        else:
            print(f'Тариф уже есть: {existing.name}')

        for s in squads:
            existing_squad = (
                await db.execute(select(ServerSquad).where(ServerSquad.squad_uuid == s['uuid']))
            ).scalar_one_or_none()
            if existing_squad is None:
                db.add(ServerSquad(squad_uuid=s['uuid'], name=s['name'], country=s.get('country')))
                print(f'Добавлен сквад: {s["name"]} ({s["uuid"]})')

        await db.commit()


if __name__ == '__main__':
    asyncio.run(seed())
