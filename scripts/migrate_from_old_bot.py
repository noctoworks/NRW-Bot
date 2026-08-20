"""Разовый перенос данных из старой базы (remnawave-bedolaga-telegram-bot,
100+ таблиц) в bedolaga-lite (14 моделей, см. app/database/models.py).

Переносим: users, subscriptions (по одной самой актуальной на юзера — у нас
Subscription.user_id уникален, мульти-тарифность старого бота не поддерживаем),
transactions (история для LTV/аналитики), referral_earnings, promo_groups.
Всё остальное — тикеты, купоны, wheel of fortune, Apple IAP, провайдер-специфичные
таблицы платежей (yookassa/heleket/mulenpay/...), автоплатежи и т.д. — в
bedolaga-lite не существует как концепция и не переносится. Явно НЕ переносим
Payment (провайдерские pending/webhook-записи) — для истории платежей достаточно
Transaction, а Payment.raw_payload/external_id старых провайдеров всё равно не
совместимы с новыми (Platega-only, см. диалог).

Remnawave НЕ трогаем — ничего не создаём и не меняем в панели. Единственная
задача — восстановить у нового User.remnawave_uuid ссылку на УЖЕ существующего
там пользователя, чтобы не плодить новые VPN-аккаунты при следующей покупке/
синхронизации.

ВАЖНО (проверено на реальном ответе панели, 2026-08-19 — предыдущая версия этого
докстринга/кода была основана на устаревшем контракте, см. app/external/remnawave/
real.py:7-17 "это меняли предыдущий агент по ошибке — не возвращать обратно"):
после апгрейда панели (коммит "replace all users routes to use id instead of
uuid", июль 2026, уже в стабильных релизах) поле `uuid` из ответа GET /users
ПРОПАЛО ВООБЩЕ — там только `id: number` + `shortUuid`. Живой резолв через
GET /api/users/by-id/{id} в ожидании поля `uuid` в ответе больше не работает
(вернёт None на каждой строке). Правильный текущий контракт: remnawave_uuid в
нашей БД — это просто str(remnawave_id) старой базы, БЕЗ каких-либо API-запросов
к панели. Старое легаси-поле users.remnawave_uuid (настоящий UUID-формат) больше
не резолвится панелью и не используется.

Предусловия:
  - .env новой базы (DATABASE_URL) указывает на ЦЕЛЕВОЙ Postgres, alembic upgrade
    head уже прогнан, в базе есть хотя бы один Tariff (см. scripts/seed.py) —
    остальные тарифы (Семейный/Корпоративный/Легаси и т.д.) скрипт создаёт сам
    по именам старых тарифов, см. ниже.
  - REMNAWAVE_BASE_URL этого бота указывает на ТУ ЖЕ панель, где физически жили
    старые аккаунты — иначе перенесённый remnawave_uuid будет числом с чужой
    панели и все действия с юзером (продление/устройства/enable) будут падать
    404/400. Никакого сетевого запроса к панели сам скрипт не делает.

Запуск (dry-run по умолчанию показывает, что будет сделано, без записи):
    OLD_DATABASE_URL=postgresql://user:pass@host/old_db \\
    .venv/Scripts/python.exe scripts/migrate_from_old_bot.py --dry-run

    # реальный прогон:
    OLD_DATABASE_URL=postgresql://user:pass@host/old_db \\
    .venv/Scripts/python.exe scripts/migrate_from_old_bot.py

Идемпотентность: юзеры матчатся по telegram_id (unique в обеих базах) — повторный
запуск не создаёт дублей среди уже перенесённых, только досоздаёт то, чего не было
(включая backfill remnawave_uuid/email на уже перенесённых). Subscription тоже
безопасен при повторном запуске — пропускается, если у юзера уже есть подписка.
Transaction/ReferralEarning НЕ дедуплицируются по контенту (в старой базе нет
стабильного внешнего ключа, который можно было бы сверить) — если процесс упал
ПОСЛЕ переноса транзакций одного юзера и перезапущен, транзакции этого юзера
задвоятся. Чтобы ограничить масштаб такого сбоя, скрипт коммитит per-user
(одна транзакция БД на одного старого юзера), а не всё разом в конце.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
from sqlalchemy import select

from app.database.database import AsyncSessionLocal
from app.database.models import PromoGroup, ReferralEarning, Subscription, Tariff, Transaction, User

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('migrate')

# Старые статусы подписки, которые считаем "живыми" при выборе, какую ИЗ
# НЕСКОЛЬКИХ старых Subscription переносить (у нас на юзера ровно одна) —
# см. User.subscription property в старой модели (app/database/models.py:2126).
_LIVE_STATUSES = ('active', 'trial', 'limited')


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Только посчитать/показать, ничего не писать в новую БД')
    args = parser.parse_args()

    old_dsn = os.environ.get('OLD_DATABASE_URL')
    if not old_dsn:
        raise SystemExit('Задайте OLD_DATABASE_URL (postgresql://... старой базы)')

    old_conn = await asyncpg.connect(old_dsn)
    try:
        await _run(old_conn, dry_run=args.dry_run)
    finally:
        await old_conn.close()


async def _run(old_conn: asyncpg.Connection, *, dry_run: bool) -> None:
    async with AsyncSessionLocal() as db:
        any_tariff = (await db.execute(select(Tariff.id).limit(1))).scalar_one_or_none()
        if any_tariff is None:
            raise SystemExit('В новой базе нет ни одного тарифа — сначала прогоните scripts/seed.py')

        # === Тарифы: old tariff_id -> new tariff_id, по имени. Тариф без аналога
        # (например "Корпоративный") создаётся новым, неактивным — только чтобы
        # существующие подписчики не потеряли обозначение своего плана; новым
        # покупателям такой тариф не показывается. NULL tariff_id старой подписки
        # (легаси/до введения тарифов) — отдельный тариф-заглушка "Легаси". ===
        old_tariffs = await old_conn.fetch('SELECT id, name, device_limit FROM tariffs')
        existing_tariff_by_name = {
            name: tid for tid, name in (await db.execute(select(Tariff.id, Tariff.name))).all()
        }
        old_tariff_id_to_new: dict[int | None, int] = {}
        for row in old_tariffs:
            name = row['name']
            if name in existing_tariff_by_name:
                new_id = existing_tariff_by_name[name]
            else:
                t = Tariff(name=name, period_prices_kopeks={}, traffic_limit_gb=0,
                            device_limit=row['device_limit'] or 3, squad_uuids=[], is_active=False)
                db.add(t)
                await db.flush()
                existing_tariff_by_name[name] = t.id
                new_id = t.id
                logger.info('Тариф создан (для существующих подписчиков, неактивный): %s', name)
            old_tariff_id_to_new[row['id']] = new_id

        legacy_name = 'Легаси (перенесено из старого бота)'
        if legacy_name in existing_tariff_by_name:
            legacy_tariff_id = existing_tariff_by_name[legacy_name]
        else:
            t = Tariff(name=legacy_name, period_prices_kopeks={}, traffic_limit_gb=0,
                        device_limit=5, squad_uuids=[], is_active=False)
            db.add(t)
            await db.flush()
            legacy_tariff_id = t.id
            logger.info('Тариф создан (для существующих подписчиков, неактивный): %s', legacy_name)
        old_tariff_id_to_new[None] = legacy_tariff_id
        if not dry_run:
            await db.commit()

        # === Промогруппы: id старой -> id новой (по имени, создаём при отсутствии) ===
        old_groups = await old_conn.fetch('SELECT id, name, server_discount_percent FROM promo_groups')
        promo_group_id_map: dict[int, int] = {}
        for row in old_groups:
            existing = (await db.execute(select(PromoGroup).where(PromoGroup.name == row['name']))).scalar_one_or_none()
            if existing is None:
                # server_discount_percent — ближайший аналог "скидки на всю подписку"
                # у нас (флэт-скидка, без разбивки по серверам/трафику/устройствам,
                # см. диалог/PromoGroup в app/database/models.py). traffic_/device_
                # discount_percent старой группы теряются осознанно — нет колонки-аналога.
                existing = PromoGroup(name=row['name'], discount_percent=row['server_discount_percent'] or 0)
                db.add(existing)
                await db.flush()
                logger.info('Промогруппа создана: %s (%s%%)', row['name'], existing.discount_percent)
            promo_group_id_map[row['id']] = existing.id
        if not dry_run:
            await db.commit()

        # === Пользователи ===
        # status != 'deleted' — уважаем удаление аккаунта в старом боте, не
        # воскрешаем такие записи при переносе.
        old_users = await old_conn.fetch(
            "SELECT id, telegram_id, username, email, language, balance_kopeks, referral_code, referred_by_id, "
            "remnawave_id, promo_group_id, referral_commission_percent, "
            "has_had_paid_subscription, status, created_at "
            "FROM users WHERE telegram_id IS NOT NULL AND status != 'deleted' ORDER BY id"
        )
        skipped_email_only = await old_conn.fetchval('SELECT count(*) FROM users WHERE telegram_id IS NULL')
        skipped_deleted = await old_conn.fetchval(
            "SELECT count(*) FROM users WHERE telegram_id IS NOT NULL AND status = 'deleted'"
        )
        total_old_users = len(old_users) + skipped_email_only + skipped_deleted

        old_id_to_new_id: dict[int, int] = {}
        pending_referred_by: dict[int, int] = {}  # new_user_id -> old_referred_by_id (второй проход)
        created, updated, email_backfilled = 0, 0, 0

        for row in old_users:
            telegram_id = row['telegram_id']
            existing = (await db.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()

            # remnawave_uuid = str(remnawave_id) панели, без резолва по API (см. докстринг).
            remnawave_uuid = str(row['remnawave_id']) if row['remnawave_id'] else None
            is_blocked = row['status'] == 'blocked'

            lang = (row['language'] or 'ru')[:2]
            if lang not in ('ru', 'en'):
                lang = 'ru'

            if existing is None:
                referral_code = row['referral_code']
                if referral_code:
                    referral_code = referral_code[:16]
                    clash = (
                        await db.execute(select(User.id).where(User.referral_code == referral_code))
                    ).scalar_one_or_none()
                    if clash is not None:
                        referral_code = None  # перегенерируется ниже
                if not referral_code:
                    from app.services.referral_service import generate_referral_code

                    for _ in range(10):
                        candidate = generate_referral_code()
                        clash = (
                            await db.execute(select(User.id).where(User.referral_code == candidate))
                        ).scalar_one_or_none()
                        if clash is None:
                            referral_code = candidate
                            break

                new_user = User(
                    telegram_id=telegram_id,
                    username=row['username'],
                    email=row['email'],
                    language=lang,
                    balance_kopeks=row['balance_kopeks'] or 0,
                    referral_code=referral_code,
                    remnawave_uuid=remnawave_uuid,
                    promo_group_id=promo_group_id_map.get(row['promo_group_id']),
                    referral_commission_percent=row['referral_commission_percent'],
                    trial_used=bool(row['has_had_paid_subscription']),
                    is_blocked=is_blocked,
                )
                db.add(new_user)
                await db.flush()
                created += 1
                old_id_to_new_id[row['id']] = new_user.id
                if row['referred_by_id']:
                    pending_referred_by[new_user.id] = row['referred_by_id']
            else:
                old_id_to_new_id[row['id']] = existing.id
                if remnawave_uuid and not existing.remnawave_uuid:
                    existing.remnawave_uuid = remnawave_uuid
                    updated += 1
                if row['email'] and not existing.email:
                    existing.email = row['email']
                    email_backfilled += 1

        # Второй проход: referred_by_id (self-FK, требует, чтобы ВСЕ юзеры уже
        # существовали — иначе циклические/форвардные ссылки не резолвились бы).
        for new_user_id, old_referrer_id in pending_referred_by.items():
            new_referrer_id = old_id_to_new_id.get(old_referrer_id)
            if new_referrer_id is None:
                continue
            user_obj = await db.get(User, new_user_id)
            user_obj.referred_by_id = new_referrer_id

        logger.info(
            'Пользователи: %s всего в старой базе (%s email-only, %s deleted пропущено), создано %s, '
            'обновлено (remnawave_uuid) %s, email добавлен %s',
            total_old_users,
            skipped_email_only,
            skipped_deleted,
            created,
            updated,
            email_backfilled,
        )
        if not dry_run:
            await db.commit()
        else:
            await db.rollback()
            logger.info('--dry-run: пользователи НЕ записаны, дальше подписки/транзакции считаются от той же выборки')

        # === Подписки (одна самая актуальная на юзера) + транзакции + рефералка —
        # по одному старому юзеру за раз, с покоммитным флашем (см. докстринг). ===
        subs_created, tx_created, earnings_created = 0, 0, 0
        for row in old_users:
            new_user_id = old_id_to_new_id.get(row['id'])
            if new_user_id is None or dry_run:
                continue

            already_has_sub = (
                await db.execute(select(Subscription.id).where(Subscription.user_id == new_user_id))
            ).scalar_one_or_none()
            if already_has_sub is None:
                sub_row = await old_conn.fetchrow(
                    "SELECT status, is_trial, tariff_id, end_date, traffic_limit_gb, traffic_used_gb, device_limit, "
                    "subscription_url, remnawave_short_uuid, autopay_enabled "
                    "FROM subscriptions WHERE user_id = $1 "
                    "ORDER BY (status IN ('active','trial','limited')) DESC, created_at DESC LIMIT 1",
                    row['id'],
                )
                if sub_row is not None:
                    old_status = sub_row['status']
                    new_status = 'active' if old_status in _LIVE_STATUSES else (
                        'disabled' if old_status == 'disabled' else 'expired'
                    )
                    db.add(
                        Subscription(
                            user_id=new_user_id,
                            tariff_id=old_tariff_id_to_new[sub_row['tariff_id']],
                            status=new_status,
                            end_date=_aware(sub_row['end_date']) or datetime.now(timezone.utc),
                            traffic_limit_gb=sub_row['traffic_limit_gb'] or 0,
                            traffic_used_gb=sub_row['traffic_used_gb'] or 0,
                            device_limit=sub_row['device_limit'] or 3,
                            subscription_url=sub_row['subscription_url'],
                            short_uuid=sub_row['remnawave_short_uuid'],
                            autopay_enabled=bool(sub_row['autopay_enabled']),
                        )
                    )
                    subs_created += 1

            tx_rows = await old_conn.fetch(
                'SELECT type, amount_kopeks, description, is_completed, created_at '
                'FROM transactions WHERE user_id = $1 ORDER BY id',
                row['id'],
            )
            for tx in tx_rows:
                db.add(
                    Transaction(
                        user_id=new_user_id,
                        type=tx['type'] if tx['type'] in ('topup', 'subscription_payment', 'referral_reward', 'refund', 'gift') else 'topup',
                        amount_kopeks=tx['amount_kopeks'],
                        status='completed' if tx['is_completed'] else 'pending',
                        description=tx['description'],
                    )
                )
                tx_created += 1

            earning_rows = await old_conn.fetch(
                'SELECT referral_id, amount_kopeks, reason FROM referral_earnings WHERE user_id = $1',
                row['id'],
            )
            for earning in earning_rows:
                source_new_id = old_id_to_new_id.get(earning['referral_id'])
                if source_new_id is None:
                    continue
                db.add(
                    ReferralEarning(
                        user_id=new_user_id,
                        source_user_id=source_new_id,
                        amount_kopeks=earning['amount_kopeks'],
                        source='purchase' if 'purchase' in (earning['reason'] or '') else 'topup',
                    )
                )
                earnings_created += 1

            await db.commit()

        logger.info(
            'Подписки создано: %s, транзакций перенесено: %s, начислений рефералки: %s',
            subs_created,
            tx_created,
            earnings_created,
        )


if __name__ == '__main__':
    asyncio.run(main())
