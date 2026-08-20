"""ОПЦИОНАЛЬНЫЙ fallback-скрипт после scripts/migrate_from_old_bot.py.

migrate_from_old_bot.py копирует subscription_url из старой БД как есть — это
работает, ПОКА публичный домен подписки на панели не менялся между старым и
новым ботом (сама панель та же, см. предусловия того скрипта). Если домен
поменялся (например бот сменил бренд/домен) — старые ссылки будут 404/не тем
доменом, и этот скрипт нужен, чтобы их поправить.

Запускать ПОСЛЕ scripts/migrate_from_old_bot.py, если после переноса
обнаружилось, что subscription_url у части юзеров не открывается.

Что делает:
  для каждого User с непустым remnawave_uuid и Subscription без subscription_url
  (или чтобы принудительно обновить все — раскомментировать фильтр ниже) —
  дёргает GET /users/{remnawave_uuid} (client.get_subscription_info) и
  подставляет живые subscription_url/short_uuid из ответа панели.

Запуск: docker compose exec bot python scripts/reconcile_migrated_subscriptions.py [--commit]
Без --commit — dry-run (печатает, что нашёл/не нашёл, ничего не пишет).
"""
import asyncio
import sys

from sqlalchemy import select

from app.config import settings
from app.database.database import AsyncSessionLocal
from app.database.models import Subscription, User
from app.external.remnawave.real import RealRemnawaveClient


async def main(commit: bool):
    if settings.REMNAWAVE_MODE != 'real':
        print('REMNAWAVE_MODE != real — нечего сверять, выход.')
        return

    client = RealRemnawaveClient(
        base_url=settings.REMNAWAVE_BASE_URL,
        api_key=settings.REMNAWAVE_API_KEY,
        panel_secret_param=settings.REMNAWAVE_PANEL_SECRET_PARAM,
    )

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Subscription, User)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.subscription_url.is_(None), User.remnawave_uuid.is_not(None))
        )).all()

        print(f'кандидатов на сверку: {len(rows)}')

        updated = 0
        not_found = 0
        errors = 0

        for sub, user in rows:
            try:
                rw = await client.get_subscription_info(remnawave_uuid=user.remnawave_uuid)
            except Exception as e:  # noqa: BLE001 — это разовый скрипт, важно не падать на первой ошибке
                print(f'user_id={user.id} telegram_id={user.telegram_id} remnawave_uuid={user.remnawave_uuid}: ОШИБКА {e}')
                errors += 1
                continue

            if not rw or not rw.subscription_url:
                not_found += 1
                continue

            sub.subscription_url = rw.subscription_url
            if rw.short_uuid:
                sub.short_uuid = rw.short_uuid
            updated += 1

        print(f'обновлено: {updated}, не найдено на панели: {not_found}, ошибок: {errors}')

        if commit:
            await db.commit()
            print('COMMITTED')
        else:
            await db.rollback()
            print('DRY RUN — rolled back, нужно передать --commit')


if __name__ == '__main__':
    asyncio.run(main(commit='--commit' in sys.argv))
