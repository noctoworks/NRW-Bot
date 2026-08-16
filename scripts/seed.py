"""Разовый сид: два тарифа (Онлайн/Семейный) + сквады из Remnawave (мок или
реальный — не важно, интерфейс один).

Цены — ПЛЕЙСХОЛДЕРЫ (кроме 1-месячной цены "Онлайн" — она взята буквально из
референс-скрина в диалоге, 444₽, чтобы курсы $/★ по умолчанию совпадали с тем,
что там показано). Поменять можно тут же или потом через админку
(handlers/admin.py, AdminTariffStates) — таблица TARIFF на это рассчитана с самого начала.

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

ONLINE_PERIOD_PRICES_KOPEKS = {
    '30': 44400,   # 444₽ — как в референс-скрине
    '90': 119900,
    '180': 219900,
    '360': 399900,
}
FAMILY_PERIOD_PRICES_KOPEKS = {
    '30': 69900,
    '90': 189900,
    '180': 349900,
    '360': 629900,
}


async def seed() -> None:
    client = get_remnawave_client()
    squads = await client.list_internal_squads()
    squad_uuids = [s['uuid'] for s in squads]

    async with AsyncSessionLocal() as db:
        existing_names = {t.name for t in (await db.execute(select(Tariff))).scalars().all()}

        if 'Онлайн' not in existing_names:
            db.add(
                Tariff(
                    name='Онлайн',
                    period_prices_kopeks=ONLINE_PERIOD_PRICES_KOPEKS,
                    traffic_limit_gb=0,  # безлимит
                    device_limit=3,
                    squad_uuids=squad_uuids,
                    is_active=True,
                )
            )
            print(f'Создан тариф "Онлайн": {ONLINE_PERIOD_PRICES_KOPEKS}')
        else:
            print('Тариф "Онлайн" уже есть')

        if 'Семейный' not in existing_names:
            db.add(
                Tariff(
                    name='Семейный',
                    period_prices_kopeks=FAMILY_PERIOD_PRICES_KOPEKS,
                    traffic_limit_gb=0,  # безлимит, отличие от "Онлайн" — только device_limit (см. диалог)
                    device_limit=6,
                    squad_uuids=squad_uuids,
                    is_active=True,
                )
            )
            print(f'Создан тариф "Семейный": {FAMILY_PERIOD_PRICES_KOPEKS}')
        else:
            print('Тариф "Семейный" уже есть')

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
